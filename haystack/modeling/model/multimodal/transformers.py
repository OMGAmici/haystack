from typing import Tuple, Set, Optional, Dict, Any, List, Union

import logging
from pathlib import Path
from abc import abstractmethod

import torch
from torch import nn
import transformers
from transformers import PreTrainedModel
from transformers.modeling_utils import SequenceSummary

from haystack.schema import ContentTypes
from haystack.errors import ModelingError
from haystack.modeling.model.multimodal.base import HaystackModel
from haystack.modeling.utils import silence_transformers_logs
from haystack.modeling.model.feature_extraction import FeatureExtractor


logger = logging.getLogger(__name__)


#: Parameters or the pooler for models that need an external pooler
POOLER_PARAMETERS: Dict[str, Dict[str, Any]] = {
    "DistilBert": {"summary_last_dropout": 0, "summary_type": "first", "summary_activation": "tanh"},
    "XLNet": {"summary_last_dropout": 0},
    "Electra": {
        "summary_last_dropout": 0,
        "summary_type": "first",
        "summary_activation": "gelu",
        "summary_use_proj": False,
    },
    "DebertaV2": {
        "summary_last_dropout": 0,
        "summary_type": "first",
        "summary_activation": "tanh",
        "summary_use_proj": False,
    },
}


class HaystackTransformerModel(nn.Module, HaystackModel):
    """
    Parent class for `transformers` models.

    These models read raw data, pass it through a feature extractor, and then return vectors that capture
    the meaning of the original data. It might also pass the output through a pooler if the model requires so.

    Models inheriting from `HaystackTransformerModel` are designed to be used in parallel one with the other
    in multimodal retrieval settings, for example image retrieval from a text query, mixed table/text retrieval, etc.
    """

    @silence_transformers_logs
    def __init__(
        self,
        pretrained_model_name_or_path: Union[str, Path],
        model_type: str,
        content_type: ContentTypes,
        model_kwargs: Optional[Dict[str, Any]] = None,
        feature_extractor_kwargs: Optional[Dict[str, Any]] = None,
        pooler_kwargs: Optional[Dict[str, Any]] = None,
    ):
        """
        :param pretrained_model_name_or_path: name of the model to load
        :param model_type: the value of model_type from the model's Config
        :param content_type: the type of data (text, image, ...) the model is supposed to process.
            See the values of `haystack.schema.ContentTypes`.
        :param model_kwargs: dictionary of parameters to pass to the model's initialization (revision, use_auth_key, etc...)
            Haystack applies some default parameters to some models. They can be overridden by users by specifying the
            desired value in this parameter. See `DEFAULT_MODEL_PARAMS`.
        :param feature_extractor_kwargs: dictionary of parameters to pass to the feature extractor's initialization (revision, use_auth_key, etc...)
            Haystack applies some default parameters to some models. They can be overridden by users by specifying the
            desired value in this parameter. See `DEFAULT_EXTRACTION_PARAMS`.
        :param pooler_kwargs: dictionary of parameters to pass to the pooler's initialization (summary_last_dropout, summary_activation, etc...)
            Haystack applies some default parameters to some models. They can be overridden by users by specifying the
            desired value in this parameter. See `POOLER_PARAMETERS`.
        """
        super().__init__(
            pretrained_model_name_or_path=pretrained_model_name_or_path,
            model_type=model_type,
            content_type=content_type,
        )

        model_class: PreTrainedModel = getattr(transformers, model_type, None)
        self.model = model_class.from_pretrained(str(pretrained_model_name_or_path), **(model_kwargs or {}))

        # Create a feature extractor
        feature_extractor_kwargs = {"do_lower_case": True, **(feature_extractor_kwargs or {})}
        self.feature_extractor = FeatureExtractor(
            pretrained_model_name_or_path=pretrained_model_name_or_path, **feature_extractor_kwargs
        )

        # The models with an entry in POOLER_PARAMETERS do not provide a pooled_output by default.
        if POOLER_PARAMETERS.get(self.model_type, None) is not None or pooler_kwargs is not None:

            # FIXME: We used to not have a dropout in the end of the pooler, because it was done in the prediction head.
            #   Double-check if we need to add it here.
            sequence_summary_config = {**POOLER_PARAMETERS.get(self.model_type, {}), **(pooler_kwargs or {})}
            for key, value in sequence_summary_config.items():
                setattr(self.model.config, key, value)

            self.pooler = SequenceSummary(self.model.config)
            self.pooler.apply(self.model._init_weights)

        # Put model in evaluation/inference mode (in contrast with training mode)
        self.model.eval()

    def to(self, devices: Optional[List[torch.device]]) -> None:
        """
        Send the model to the specified PyTorch device(s)
        """
        if devices:
            if len(devices) > 1:
                self.model = nn.DataParallel(self.model, device_ids=devices)
            else:
                self.model.to(devices[0])

    @property
    @abstractmethod
    def expected_inputs(self) -> Tuple[Set[str], Set[str]]:
        """
        Returns a tuple, (List[mandatory arg names], List[optional arg names])
        """
        raise NotImplementedError("Abstract method, use a subclass.")

    def get_features(self, data: List[Any], extraction_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Convert raw data into the model's input tensors using a proper feature extractor.
        """
        features = self.feature_extractor(data=data, **(extraction_params or {}))
        if not features:
            raise ModelingError(
                f"Could not extract features for data of type {self.content_type}. "
                f"Check that your feature extractor ({self.feature_extractor}) is correct for this data type."
            )
        return features

    def encode(self, data: List[Any], **kwargs) -> torch.Tensor:
        """
        Generate the tensors representing the input data.

        Validates the inputs according to what the subclass declared in the `expected_inputs` property.
        Then passes the vectors to the `_forward()` method and returns its output untouched.
        """
        inputs = self.get_features(data=data)

        # Check if the inputs are correct TODO verify, does this check still makes sense to keep?
        mandatory_args, optional_args = self.expected_inputs
        all_args = mandatory_args | optional_args
        given_args = set(inputs.keys())
        if given_args <= mandatory_args or given_args >= all_args:
            raise ModelingError(
                "The features extracted from the data do not match the model's expectations.\n"
                f"Input names: {', '.join(sorted(kwargs.keys()))}\n"
                f"Expected: {', '.join(sorted(all_args))} (where {', '.join(sorted(mandatory_args))} are mandatory)"
            )

        # The actual encoding step
        with torch.no_grad():
            output = self._forward(**inputs)
        return output

    def _forward(self, **kwargs) -> torch.Tensor:
        """
        The default forward() implementation. Simply returns the pooler_output field of the output of the model's
        forward pass, using the external pooler if the model does not provide one.
        """
        output = self.model(**kwargs)
        if self.pooler:
            return self.pooler(output[0])
        return output.pooler_output


class HaystackTextTransformerModel(HaystackTransformerModel):
    """
    Class wrapping `transformers` models that handle text data.

    Models using this wrapper should accept "input_ids", "token_type_ids", "attention_mask" as
    input vector for their forward pass.
    """

    def __init__(
        self,
        pretrained_model_name_or_path: str,
        model_type: str,
        content_type: ContentTypes = "text",
        model_kwargs: Optional[Dict[str, Any]] = None,
        feature_extractor_kwargs: Optional[Dict[str, Any]] = None,
    ):
        if content_type != "text":
            raise ModelingError(
                f"{pretrained_model_name_or_path} (type {model_type}) can't handle "
                f"data of type {content_type} or is not supported by Haystack."
            )

        super().__init__(
            pretrained_model_name_or_path=pretrained_model_name_or_path,
            model_type=model_type,
            content_type="text",
            model_kwargs=model_kwargs,
            feature_extractor_kwargs=feature_extractor_kwargs,
        )

    @property
    def expected_inputs(self) -> Tuple[Set[str], Set[str]]:
        return {"input_ids", "token_type_ids", "attention_mask"}, set()

    @property
    def embedding_dim(self):
        return self.dim


class HaystackImageTransformerModel(HaystackTransformerModel):
    """
    Class wrapping `transformers` models that handle image data.

    Models using this wrapper should accept "pixel_values" as input vector for their forward pass,
    and may take "bool_masked_pos" and "head_mask" as well.
    """

    # FIXME verify if these optional vectors are ever used. We might want to have two separate
    # ImageTransformers classes requiring two different sets of vectors.
    def __init__(
        self,
        pretrained_model_name_or_path: str,
        model_type: str,
        content_type: ContentTypes = "image",
        model_kwargs: Optional[Dict[str, Any]] = None,
        feature_extractor_kwargs: Optional[Dict[str, Any]] = None,
    ):
        if content_type != "image":
            raise ModelingError(
                f"{pretrained_model_name_or_path} can't handle data of type "
                f"{content_type} or is not supported by Haystack."
            )

        super().__init__(
            pretrained_model_name_or_path=pretrained_model_name_or_path,
            model_type=model_type,
            content_type="image",
            model_kwargs=model_kwargs,
            feature_extractor_kwargs=feature_extractor_kwargs,
        )

    @property
    def expected_inputs(self) -> Tuple[Set[str], Set[str]]:
        return {"pixel_values"}, {"bool_masked_pos", "head_mask"}

    @property
    def embedding_dim(self) -> int:
        return self.window_size
