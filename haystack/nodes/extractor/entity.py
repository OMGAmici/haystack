import logging
from typing import List, Union, Dict, Optional, Tuple, Any

import itertools
import torch
from torch.utils.data import Dataset, DataLoader
import numpy as np

from transformers import AutoTokenizer, AutoModelForTokenClassification
from transformers import pipeline
from transformers.pipelines.token_classification import AggregationStrategy
from tokenizers.pre_tokenizers import WhitespaceSplit
from tqdm.auto import tqdm
from haystack.schema import Document
from haystack.nodes.base import BaseComponent
from haystack.modeling.utils import initialize_device_settings
from haystack.utils.torch_utils import ensure_tensor_on_device

logger = logging.getLogger(__name__)


class EntityExtractor(BaseComponent):
    """
    This node is used to extract entities out of documents.
    The most common use case for this would be as a named entity extractor.
    The default model used is elastic/distilbert-base-cased-finetuned-conll03-english.
    This node can be placed in a querying pipeline to perform entity extraction on retrieved documents only,
    or it can be placed in an indexing pipeline so that all documents in the document store have extracted entities.
    This Node will automatically split up long Documents based on the max token length of the underlying model and
    aggregate the predictions of each split to predict the final set of entities for each Document.
    The entities extracted by this Node will populate Document.meta.entities.

    :param model_name_or_path: The name of the model to use for entity extraction.
    :param model_version: The version of the model to use for entity extraction.
    :param use_gpu: Whether to use the GPU or not.
    :param progress_bar: Whether to show a progress bar or not.
    :param batch_size: The batch size to use for entity extraction.
    :param use_auth_token: The API token used to download private models from Huggingface.
                           If this parameter is set to `True`, then the token generated when running
                           `transformers-cli login` (stored in ~/.huggingface) will be used.
                           Additional information can be found here
                           https://huggingface.co/transformers/main_classes/model.html#transformers.PreTrainedModel.from_pretrained
    :param devices: List of torch devices (e.g. cuda, cpu, mps) to limit inference to specific devices.
                        A list containing torch device objects and/or strings is supported (For example
                        [torch.device('cuda:0'), "mps", "cuda:1"]). When specifying `use_gpu=False` the devices
                        parameter is not used and a single cpu device is used for inference.
    :param aggregation_strategy: The strategy to fuse (or not) tokens based on the model prediction.
        “none”: Will not do any aggregation and simply return raw results from the model.
        “simple”: Will attempt to group entities following the default schema.
                  (A, B-TAG), (B, I-TAG), (C, I-TAG), (D, B-TAG2) (E, B-TAG2) will end up being
                  [{“word”: ABC, “entity”: “TAG”}, {“word”: “D”, “entity”: “TAG2”}, {“word”: “E”, “entity”: “TAG2”}]
                  Notice that two consecutive B tags will end up as different entities.
                  On word based languages, we might end up splitting words undesirably: Imagine Microsoft being tagged
                  as [{“word”: “Micro”, “entity”: “ENTERPRISE”}, {“word”: “soft”, “entity”: “NAME”}].
                  Look at the options FIRST, MAX, and AVERAGE for ways to mitigate this example and disambiguate words
                  (on languages that support that meaning, which is basically tokens separated by a space).
                  These mitigations will only work on real words, “New york” might still be tagged with two different entities.
        “first”: (works only on word based models) Will use the SIMPLE strategy except that words, cannot end up with
                 different tags. Words will simply use the tag of the first token of the word when there is ambiguity.
        “average”: (works only on word based models) Will use the SIMPLE strategy except that words, cannot end up with
                   different tags. The scores will be averaged across tokens, and then the label with the maximum score is chosen.
        “max”: (works only on word based models) Will use the SIMPLE strategy except that words, cannot end up with
               different tags. Word entity will simply be the token with the maximum score.
    :param add_prefix_space: Do this if you do not want the first word to be treated differently. This is relevant for
        model types such as "bloom", "gpt2", and "roberta".
        Explained in more detail here:
        https://huggingface.co/docs/transformers/model_doc/roberta#transformers.RobertaTokenizer
    :param num_workers: Number of workers to be used in the Pytorch Dataloader.
    :param flatten_entities_in_meta_data: If True this converts all entities predicted for a document from a list of
        dictionaries into a single list for each key in the dictionary.
    :param max_seq_len: Max sequence length of one input text for the model. If not provided the max length is
        automatically determined by the `model_max_length` variable of the tokenizer.
    :param pre_split_text: If True split the text of a Document into words before being input into the model. This is
        common practice for models trained for named entity recognition and is recommended when using architectures that
        do not use word-level tokenizers.
    """

    outgoing_edges = 1

    def __init__(
        self,
        model_name_or_path: str = "elastic/distilbert-base-cased-finetuned-conll03-english",
        model_version: Optional[str] = None,
        use_gpu: bool = True,
        batch_size: int = 16,
        progress_bar: bool = True,
        use_auth_token: Optional[Union[str, bool]] = None,
        devices: Optional[List[Union[str, torch.device]]] = None,
        aggregation_strategy: str = "first",
        add_prefix_space: Optional[bool] = None,
        num_workers: int = 0,
        flatten_entities_in_meta_data: bool = False,
        max_seq_len: int = None,
        pre_split_text: bool = False,
    ):
        super().__init__()

        self.devices, _ = initialize_device_settings(devices=devices, use_cuda=use_gpu, multi_gpu=False)
        if len(self.devices) > 1:
            logger.warning(
                f"Multiple devices are not supported in {self.__class__.__name__} inference, "
                f"using the first device {self.devices[0]}."
            )
        self.batch_size = batch_size
        self.progress_bar = progress_bar
        self.model_name_or_path = model_name_or_path
        self.use_auth_token = use_auth_token
        self.num_workers = num_workers
        self.flatten_entities_in_meta_data = flatten_entities_in_meta_data

        if add_prefix_space is None:
            tokenizer = AutoTokenizer.from_pretrained(model_name_or_path, use_auth_token=use_auth_token)
        else:
            tokenizer = AutoTokenizer.from_pretrained(
                model_name_or_path, use_auth_token=use_auth_token, add_prefix_space=add_prefix_space
            )
        # TODO Cleanup error message and use logger.error?
        if not tokenizer.is_fast:
            raise Exception("This node only works when using a fast tokenizer")

        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len if max_seq_len else self.tokenizer.model_max_length

        self.pre_split_text = pre_split_text
        self.pre_tokenizer = WhitespaceSplit()

        self.model = AutoModelForTokenClassification.from_pretrained(
            model_name_or_path, use_auth_token=use_auth_token, revision=model_version
        )
        self.model.to(str(self.devices[0]))
        self.extractor_pipeline = pipeline(
            "ner",
            model=self.model,
            tokenizer=self.tokenizer,
            aggregation_strategy=aggregation_strategy,
            device=self.devices[0],
            use_auth_token=use_auth_token,
        )

    @staticmethod
    def _add_entities_to_doc(
        doc: Union[Document, dict], entities: List[dict], flatten_entities_in_meta_data: bool = False
    ):
        """Add the entities to the metadata of the document

        :param doc: The document where the metadata will be added.
        :param entities: The list of entities predicted for document `doc`.
        :param flatten_entities_in_meta_data: If True this converts all entities predicted for a document from a list of
            dictionaries into a single list for each key in the dictionary.
        """
        is_doc = isinstance(doc, Document)
        if flatten_entities_in_meta_data:
            new_key_map = {
                "entity_group": "entity_groups",
                "score": "entity_scores",
                "word": "entity_words",
                "start": "entity_starts",
                "end": "entity_ends",
            }
            entity_lists: Dict[str, List[Any]] = {v: [] for k, v in new_key_map.items()}
            for entity in entities:
                for key in entity:
                    new_key = new_key_map[key]
                    if isinstance(entity[key], np.float32):
                        entity_lists[new_key].append(float(entity[key]))
                    else:
                        entity_lists[new_key].append(entity[key])
            if is_doc:
                doc.meta.update(entity_lists)  # type: ignore
            else:
                doc["meta"].update(entity_lists)  # type: ignore
        else:
            if is_doc:
                doc.meta["entities"] = entities  # type: ignore
            else:
                doc["meta"]["entities"] = entities  # type: ignore

    def run(self, documents: Optional[Union[List[Document], List[dict]]] = None) -> Tuple[Dict, str]:  # type: ignore
        """
        This is the method called when this node is used in a pipeline
        """
        if documents:
            is_doc = isinstance(documents[0], Document)
            for doc in tqdm(documents, disable=not self.progress_bar, desc="Extracting entities"):
                # In a querying pipeline, doc is a haystack.schema.Document object
                if is_doc:
                    content = doc.content  # type: ignore
                # In an indexing pipeline, doc is a dictionary
                else:
                    content = doc["content"]  # type: ignore
                entities = self.extract(content)
                self._add_entities_to_doc(
                    doc, entities=entities, flatten_entities_in_meta_data=self.flatten_entities_in_meta_data
                )
        output = {"documents": documents}
        return output, "output_1"

    def run_batch(self, documents: Union[List[Document], List[List[Document]], List[dict], List[List[dict]]], batch_size: Optional[int] = None):  # type: ignore
        if isinstance(documents[0], (Document, dict)):
            flattened_documents = documents
        else:
            flattened_documents = list(itertools.chain.from_iterable(documents))  # type: ignore

        is_doc = isinstance(flattened_documents[0], Document)

        if batch_size is None:
            batch_size = self.batch_size

        if is_doc:
            docs = [doc.content for doc in flattened_documents]  # type: ignore
        else:
            docs = [doc["content"] for doc in flattened_documents]  # type: ignore

        all_entities = self.extract_batch(docs, batch_size=batch_size)

        for entities_per_doc, doc in zip(all_entities, flattened_documents):
            self._add_entities_to_doc(
                doc, entities=entities_per_doc, flatten_entities_in_meta_data=self.flatten_entities_in_meta_data  # type: ignore
            )

        output = {"documents": documents}
        return output, "output_1"

    def preprocess(self, sentence: List[str], offset_mapping: Optional[torch.Tensor] = None):
        """Preprocessing step to tokenize the provided text.

        :param sentence: List of text to tokenize. This expects a list of texts.
        :param offset_mapping: Only needed if a slow tokenizer is used. Will be used in the postprocessing step to
            determine the original character positions of the detected entities.
        """
        text_to_tokenize = sentence
        if self.pre_split_text:
            word_offset_mapping = [self.pre_tokenizer.pre_tokenize_str(t) for t in sentence]
            text_to_tokenize = [[word_with_pos[0] for word_with_pos in text] for text in word_offset_mapping]

        model_inputs = self.tokenizer(
            text_to_tokenize,
            return_tensors="pt",
            return_special_tokens_mask=True,
            return_offsets_mapping=True,
            return_overflowing_tokens=True,
            padding="max_length",
            truncation=True,
            max_length=self.max_seq_len,
            is_split_into_words=self.pre_split_text,
        )
        if offset_mapping is not None:
            model_inputs["offset_mapping"] = offset_mapping

        model_inputs["sentence"] = sentence
        if self.pre_split_text:
            model_inputs["word_offset_mapping"] = word_offset_mapping

        return model_inputs

    def forward(self, model_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Forward step

        :param model_inputs: Dictionary of inputs to be given to the model.
        """
        special_tokens_mask = model_inputs.pop("special_tokens_mask")
        offset_mapping = model_inputs.pop("offset_mapping", None)
        overflow_to_sample_mapping = model_inputs.pop("overflow_to_sample_mapping")
        sentence = model_inputs.pop("sentence")

        logits = self.model(**model_inputs)[0]

        return {
            "logits": logits,
            "special_tokens_mask": special_tokens_mask,
            "offset_mapping": offset_mapping,
            "overflow_to_sample_mapping": overflow_to_sample_mapping,
            "sentence": sentence,
            **model_inputs,
        }

    def postprocess(self, model_outputs_grouped_by_doc: List[Dict[str, Any]]) -> List[List[Dict]]:
        """Pass the model outputs grouped by doc to `self.extractor_pipeline.postprocess` to take advantage of the
        advanced postprocessing features available in the HuggingFace TokenClassificationPipeline object.

        :param model_outputs_grouped_by_doc: model outputs grouped by Document
        """
        results_per_doc = []
        num_docs = len(model_outputs_grouped_by_doc)
        for i in range(num_docs):
            results = self._postprocess(model_outputs_grouped_by_doc[i], **self.extractor_pipeline._postprocess_params)
            results_per_doc.append(results)
        return results_per_doc

    def _postprocess(
        self,
        model_outputs: Dict[str, Any],
        aggregation_strategy: AggregationStrategy = AggregationStrategy.NONE,
        ignore_labels: List[str] = None,
    ):
        """The same postprocessing method as `transformers.TokenClassificationPipeline.postprocess` except that we use
        the locally defined `self._gather_pre_entities` method instead of the
        `transformers.TokenClassificationPipeline.gather_pre_entities` method because subwords are determined
        differently.

        :param model_outputs: Model outputs for a single Document.
        :param aggregation_strategy: The strategy to fuse (or not) tokens based on the model prediction.
        :param ignore_labels: list of labels to ignore
        """
        if ignore_labels is None:
            ignore_labels = ["O"]
        logits = model_outputs["logits"][0].numpy()
        sentence = model_outputs["sentence"]
        input_ids = model_outputs["input_ids"][0]
        offset_mapping = model_outputs["offset_mapping"][0].numpy()
        special_tokens_mask = model_outputs["special_tokens_mask"][0].numpy()
        word_ids = model_outputs["word_ids"]

        maxes = np.max(logits, axis=-1, keepdims=True)
        shifted_exp = np.exp(logits - maxes)
        scores = shifted_exp / shifted_exp.sum(axis=-1, keepdims=True)

        updated_offset_mapping = offset_mapping
        pre_entities = self._gather_pre_entities(
            sentence, input_ids, scores, updated_offset_mapping, special_tokens_mask, word_ids
        )
        entities = self._aggregate(pre_entities, aggregation_strategy)

        if self.pre_split_text:
            word_offset_mapping = model_outputs["word_offset_mapping"]
            entities = self._update_character_spans(entities, word_offset_mapping)

        # Only group entities if aggregation strategy is not None
        if aggregation_strategy == AggregationStrategy.NONE:
            grouped_entities = entities
        else:
            grouped_entities = self.extractor_pipeline.group_entities(entities)

        # Filter anything that is in self.ignore_labels
        entities = [
            entity
            for entity in grouped_entities
            if entity.get("entity", None) not in ignore_labels and entity.get("entity_group", None) not in ignore_labels
        ]
        return entities

    def _aggregate(self, pre_entities: List[dict], aggregation_strategy: AggregationStrategy) -> List[dict]:
        if aggregation_strategy in {AggregationStrategy.NONE, AggregationStrategy.SIMPLE}:
            entities = []
            for pre_entity in pre_entities:
                entity_idx = pre_entity["scores"].argmax()
                score = pre_entity["scores"][entity_idx]
                entity = {
                    "entity": self.model.config.id2label[entity_idx],
                    "score": score,
                    "index": pre_entity["index"],
                    "word": pre_entity["word"],
                    "start": pre_entity["start"],
                    "end": pre_entity["end"],
                }
                entities.append(entity)
        else:
            entities = self.extractor_pipeline.aggregate_words(pre_entities, aggregation_strategy)

        return entities

    def _update_character_spans(self, word_entities: List[Dict[str, Any]], word_offset_mapping: List[Tuple]):
        """
        :param word_entities: entity predictions per word
        :param word_offset_mapping:
        """
        if len(word_entities) != len(word_offset_mapping):
            logger.warning(
                "Unable to determine the character spans of the entities in the original text."
                " Returning entities as is."
            )
            return word_entities

        entities = []
        for idx, entity in enumerate(word_entities):
            word, (start, end) = word_offset_mapping[idx]
            entity["start"] = start
            entity["end"] = end
            entities.append(entity)

        return entities

    def _gather_pre_entities(
        self,
        sentence: Union[str, List[str]],
        input_ids: np.ndarray,
        scores: np.ndarray,
        offset_mapping: np.ndarray,
        special_tokens_mask: np.ndarray,
        word_ids: List,
    ):
        """A modified version of `transformers.TokenClassificationPipeline.gather_pre_entities` method. This method
        determines subwords using `word_ids` instead of heuristics.

        :param sentence: The original text. Can be a list of words if `self.pre_split_text` is set to True.
        :param input_ids:
        :param scores:
        :param offset_mapping:
        :param special_tokens_mask:
        :param word_ids: List of integers or None types that provides the token index to word id mapping. None types
            correspond to special tokens.
        """
        previous_word_id = -1
        pre_entities = []
        for token_idx, token_scores in enumerate(scores):
            current_word_id = word_ids[token_idx]

            # Filter special_tokens, they should only occur
            # at the sentence boundaries since we're not encoding pairs of
            # sentences so we don't have to keep track of those.
            if special_tokens_mask[token_idx]:
                continue

            word = self.tokenizer.convert_ids_to_tokens(int(input_ids[token_idx]))

            if current_word_id != previous_word_id:
                is_subword = False
            else:
                is_subword = True

            start_ind, end_ind = offset_mapping[token_idx]
            if int(input_ids[token_idx]) == self.tokenizer.unk_token_id:
                if isinstance(sentence, list):
                    word = sentence[current_word_id][start_ind:end_ind]
                else:
                    word = sentence[start_ind:end_ind]
                is_subword = False

            pre_entity = {
                "word": word,
                "scores": token_scores,
                "start": start_ind,
                "end": end_ind,
                "index": token_idx,
                "is_subword": is_subword,
            }
            pre_entities.append(pre_entity)

            previous_word_id = current_word_id
        return pre_entities

    def _group_predictions_by_doc(
        self, model_outputs: Dict[str, Any], word_ids: List[List], word_offset_mapping: List[List[Tuple]] = None
    ) -> List[Dict[str, Any]]:
        """Aggregate each of the items in `model_outputs` based on which Document they originally came from.

        :param model_outputs: Dictionary of model outputs
        :param word_ids: List of list of integers or None types that provides the token index to word id mapping.
            None types correspond to special tokens. The shape is (num_splits_per_doc * num_docs) x model_max_length.
        :param word_offset_mapping: num_docs x num_words_per_doc
        """
        # overflow_to_sample_mapping tells me which documents need be aggregated
        # e.g. model_outputs['overflow_to_sample_mapping'] = [0, 0, 1, 1, 1, 1] means first two elements of
        # predictions belong to document 0 and the other four elements belong to document 1.
        sample_mapping = model_outputs["overflow_to_sample_mapping"]
        all_num_splits_per_doc = torch.zeros(sample_mapping[-1] + 1, dtype=torch.long)
        for idx in sample_mapping:
            all_num_splits_per_doc[idx] += 1

        logits = model_outputs["logits"]  # (num_splits_per_doc * num_docs) x model_max_length x num_classes
        input_ids = model_outputs["input_ids"]  # (num_splits_per_doc * num_docs) x model_max_length
        offset_mapping = model_outputs["offset_mapping"]  # (num_splits_per_doc * num_docs) x model_max_length x 2
        special_tokens_mask = model_outputs["special_tokens_mask"]  # (num_splits_per_doc * num_docs) x model_max_length
        sentence = model_outputs["sentence"]  # num_docs x length of text

        model_outputs_grouped_by_doc = []
        bef_idx = 0
        for i, num_splits_per_doc in enumerate(all_num_splits_per_doc):
            aft_idx = bef_idx + num_splits_per_doc

            logits_per_doc = logits[bef_idx:aft_idx].reshape(
                1, -1, logits.shape[2]
            )  # 1 x (num_splits_per_doc * model_max_length) x num_classes
            input_ids_per_doc = input_ids[bef_idx:aft_idx].reshape(1, -1)  # 1 x (num_splits_per_doc * model_max_length)
            offset_mapping_per_doc = offset_mapping[bef_idx:aft_idx].reshape(
                1, -1, offset_mapping.shape[2]
            )  # 1 x (num_splits_per_doc * model_max_length) x 2
            special_tokens_mask_per_doc = special_tokens_mask[bef_idx:aft_idx].reshape(
                1, -1
            )  # 1 x (num_splits_per_doc * model_max_length)
            sentence_per_doc = sentence[i]
            word_ids_per_doc = list(
                itertools.chain.from_iterable(word_ids[bef_idx:aft_idx])
            )  # 1 x (num_splits_per_doc * model_max_length)
            if word_offset_mapping is not None:
                word_offset_mapping_per_doc = word_offset_mapping[i]  # 1 x num_words_per_doc

            bef_idx += num_splits_per_doc

            output = {
                "logits": logits_per_doc,
                "sentence": sentence_per_doc,
                "input_ids": input_ids_per_doc,
                "offset_mapping": offset_mapping_per_doc,
                "special_tokens_mask": special_tokens_mask_per_doc,
                "word_ids": word_ids_per_doc,
            }
            if word_offset_mapping is not None:
                output["word_offset_mapping"] = word_offset_mapping_per_doc

            model_outputs_grouped_by_doc.append(output)
        return model_outputs_grouped_by_doc

    def _flatten_predictions(self, predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Flatten the predictions across the batch dimension.

        :param predictions: List of model output dictionaries
        """
        flattened_predictions: Dict[str, Any] = {
            "logits": [],
            "input_ids": [],
            "special_tokens_mask": [],
            "offset_mapping": [],
            "overflow_to_sample_mapping": [],
            "sentence": [],
        }
        for pred in predictions:
            flattened_predictions["logits"].append(pred["logits"])
            flattened_predictions["input_ids"].append(pred["input_ids"])
            flattened_predictions["special_tokens_mask"].append(pred["special_tokens_mask"])
            flattened_predictions["offset_mapping"].append(pred["offset_mapping"])
            flattened_predictions["overflow_to_sample_mapping"].append(pred["overflow_to_sample_mapping"])
            flattened_predictions["sentence"].extend(pred["sentence"])

        flattened_predictions["logits"] = torch.vstack(flattened_predictions["logits"])
        flattened_predictions["input_ids"] = torch.vstack(flattened_predictions["input_ids"])
        flattened_predictions["special_tokens_mask"] = torch.vstack(flattened_predictions["special_tokens_mask"])
        flattened_predictions["offset_mapping"] = torch.vstack(flattened_predictions["offset_mapping"])
        # Make sure to hstack overflow_to_sample_mapping since it doesn't have a batch dimension
        flattened_predictions["overflow_to_sample_mapping"] = torch.hstack(
            flattened_predictions["overflow_to_sample_mapping"]
        )
        return flattened_predictions

    def extract(self, text: Union[str, List[str]], batch_size: int = 1):
        """
        This function can be called to perform entity extraction when using the node in isolation.

        :param text: Text to extract entities from. Can be a str or a List of str.
        :param batch_size: Number of texts to make predictions on at a time.
        """
        is_single_text = False

        if isinstance(text, str):
            is_single_text = True
            text = [text]
        elif isinstance(text, list) and isinstance(text[0], str):
            pass
        else:
            raise ValueError("The variable text must be a string, or a list of strings.")

        # Preprocess
        model_inputs = self.preprocess(text)
        word_offset_mapping = model_inputs.pop("word_offset_mapping", None)
        word_ids = [model_inputs.word_ids(i) for i in range(model_inputs.input_ids.shape[0])]
        dataset = TokenClassificationDataset(model_inputs.data)
        dataloader = DataLoader(dataset, shuffle=False, batch_size=batch_size, num_workers=self.num_workers)

        # Forward
        predictions: List[Dict[str, Any]] = []
        for batch in tqdm(dataloader, disable=not self.progress_bar, total=len(dataloader), desc="Extracting entities"):
            batch = ensure_tensor_on_device(batch, device=self.devices[0])
            with torch.inference_mode():
                model_outputs = self.forward(batch)
            model_outputs = ensure_tensor_on_device(model_outputs, device=torch.device("cpu"))
            predictions.append(model_outputs)

        # Postprocess
        predictions = self._flatten_predictions(predictions)  # type: ignore
        predictions = self._group_predictions_by_doc(predictions, word_ids, word_offset_mapping)  # type: ignore
        predictions = self.postprocess(predictions)  # type: ignore

        if is_single_text:
            return predictions[0]  # type: ignore

        return predictions

    def extract_batch(self, texts: Union[List[str], List[List[str]]], batch_size: int = 1) -> List[List[Dict]]:
        """
        This function allows the extraction of entities out of a list of strings or a list of lists of strings.
        The only difference between this function and `self.extract` is that it has additional logic to handle a
        list of lists of strings.

        :param texts: List of str or list of lists of str to extract entities from.
        :param batch_size: Number of texts to make predictions on at a time.
        """
        if isinstance(texts[0], str):
            single_list_of_texts = True
            number_of_texts = [len(texts)]
        else:
            single_list_of_texts = False
            number_of_texts = [len(text_list) for text_list in texts]
            texts = list(itertools.chain.from_iterable(texts))

        entities = self.extract(texts, batch_size=batch_size)  # type: ignore

        if single_list_of_texts:
            return entities  # type: ignore
        else:
            # Group entities together
            grouped_entities = []
            left_idx = 0
            for number in number_of_texts:
                right_idx = left_idx + number
                grouped_entities.append(entities[left_idx:right_idx])
                left_idx = right_idx
            return grouped_entities


def simplify_ner_for_qa(output):
    """
    Returns a simplified version of the output dictionary
    with the following structure:
    [
        {
            answer: { ... }
            entities: [ { ... }, {} ]
        }
    ]
    The entities included are only the ones that overlap with
    the answer itself.

    :param output: Output from a query pipeline
    """
    compact_output = []
    for answer in output["answers"]:

        entities = []
        for entity in answer.meta["entities"]:
            if (
                entity["start"] >= answer.offsets_in_document[0].start
                and entity["end"] <= answer.offsets_in_document[0].end
            ):
                entities.append(entity["word"])

        compact_output.append({"answer": answer.answer, "entities": entities})
    return compact_output


class TokenClassificationDataset(Dataset):
    """Token Classification Dataset

    This is a wrapper class to create a Pytorch dataset object from the data attribute of a
    `transformers.tokenization_utils_base.BatchEncoding` object.

    :param model_inputs: The data attribute of the output from a HuggingFace tokenizer which is needed to evaluate the
        forward pass of a token classification model.
    """

    def __init__(self, model_inputs: dict):
        self.model_inputs = model_inputs
        self._len = len(model_inputs["input_ids"])

    def __getitem__(self, item):
        input_ids = self.model_inputs["input_ids"][item]
        attention_mask = self.model_inputs["attention_mask"][item]
        special_tokens_mask = self.model_inputs["special_tokens_mask"][item]
        offset_mapping = self.model_inputs["offset_mapping"][item]
        overflow_to_sample_mapping = self.model_inputs["overflow_to_sample_mapping"][item]
        sentence = self.model_inputs["sentence"][overflow_to_sample_mapping]
        single_input = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "special_tokens_mask": special_tokens_mask,
            "offset_mapping": offset_mapping,
            "overflow_to_sample_mapping": overflow_to_sample_mapping,
            "sentence": sentence,
        }
        return single_input

    def __len__(self):
        return self._len
