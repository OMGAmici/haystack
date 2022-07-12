from pydoc import Doc
from typing import List, Union, Dict, Any

import sys
from abc import ABC
from uuid import UUID
from datetime import datetime

import numpy as np
import pytest
from unittest.mock import Mock

from haystack.document_stores import BaseDocumentStore, PineconeDocumentStore
from haystack.errors import DuplicateDocumentError
from haystack.schema import Document, Label, Answer, Span
from haystack.nodes import EmbeddingRetriever

from ..conftest import SAMPLES_PATH



class TestDocumentStoresBase(ABC):

    # Fixtures

    def docs_all_formats() -> List[Union[Document, Dict[str, Any]]]:
        return [
            # metafield at the top level for backward compatibility
            {
                "content": "My name is Paul and I live in New York",
                "meta_field": "test2",
                "name": "filename2",
                "date_field": "2019-10-01",
                "numeric_field": 5.0,
                "odd_document": True
            },
            # "dict" format
            {
                "content": "My name is Carla and I live in Berlin",
                "meta": {"meta_field": "test1", "name": "filename1", "date_field": "2020-03-01", "numeric_field": 5.5, "odd_document": False},
            },
            # Document object
            Document(
                content="My name is Christelle and I live in Paris",
                meta={"meta_field": "test3", "name": "filename3", "date_field": "2018-10-01", "numeric_field": 4.5, "odd_document": True},
            ),
            Document(
                content="My name is Camila and I live in Madrid",
                meta={"meta_field": "test4", "name": "filename4", "date_field": "2021-02-01", "numeric_field": 3.0, "odd_document": False},
            ),
            Document(
                content="My name is Matteo and I live in Rome",
                meta={"meta_field": "test5", "name": "filename5", "date_field": "2019-01-01", "numeric_field": 0.0, "odd_document": True},
            ),
        ]

    @pytest.fixture
    def docs(docs_all_formats) -> List[Document]:
        return [Document.from_dict(doc) if isinstance(doc, dict) else doc for doc in docs_all_formats]


    @pytest.fixture
    def docs_with_ids(docs) -> List[Document]:
        # Should be already sorted
        uuids = [
            UUID("190a2421-7e48-4a49-a639-35a86e202dfb"),
            UUID("20ff1706-cb55-4704-8ae8-a3459774c8dc"),
            UUID("5078722f-07ae-412d-8ccb-b77224c4bacb"),
            UUID("81d8ca45-fad1-4d1c-8028-d818ef33d755"),
            UUID("f985789f-1673-4d8f-8d5f-2b8d3a9e8e23"),
        ]
        uuids.sort()
        for doc, uuid in zip(docs, uuids):
            doc.id = str(uuid)
        return docs


    @pytest.fixture
    def docs_with_random_emb(docs) -> List[Document]:
        for doc in docs:
            doc.embedding = np.random.random([768])
        return docs


    @pytest.fixture
    def docs_with_true_emb():
        return [
            Document(
                content="The capital of Germany is the city state of Berlin.",
                embedding=np.loadtxt(SAMPLES_PATH / "embeddings" / "embedding_1.txt"),
            ),
            Document(
                content="Berlin is the capital and largest city of Germany by both area and population.",
                embedding=np.loadtxt(SAMPLES_PATH / "embeddings" / "embedding_2.txt"),
            ),
        ]

    @pytest.fixture
    def duplicate_docs(self) -> List[Document]:
        """
        This fixture provides a list containing two docs which IDs will be the same.
        """
        return [
            Document(content="Doc1", id_hash_keys=["content"]),
            Document(content="Doc1", id_hash_keys=["content"]),
        ]

    @pytest.fixture
    def duplicate_docs_hash_key(self) -> List[Document]:
        """
        This fixture provides a list containing two docs with the same content, 
        with different ID due to the hash_key param.
        """
        return [
            Document(content="Doc1", meta={"key_1": "0"}, id_hash_keys=["meta"]),
            Document(content="Doc1", meta={"key_1": "1"}, id_hash_keys=["meta"]),
            Document(content="Doc2", meta={"key_2": "0"}, id_hash_keys=["meta"]),
        ]
    

    @pytest.fixture
    def doc_store(self) -> BaseDocumentStore:
        """
        This fixture provides an empty document store and takes care of cleaning up after each test
        """
        raise NotImplementedError


    def doc_store_with_docs(self, doc_store: BaseDocumentStore, docs: List[Document]) -> BaseDocumentStore:
        """
        This fixture provides a pre-populated document store and takes care of cleaning up after each test
        """
        doc_store.write_documents(docs)
        return doc_store

    #
    # Tests
    #

    def test_write_with_duplicate_doc_ids_skip(doc_store: BaseDocumentStore, duplicate_docs: List[Document]):
        doc_store.write_documents(duplicate_docs, duplicate_docs="skip")
        assert len(doc_store.get_all_documents()) == 1


    def test_write_with_duplicate_doc_ids_fail(doc_store: BaseDocumentStore, duplicate_docs: List[Document]):
        with pytest.raises(DuplicateDocumentError):
            doc_store.write_documents(duplicate_docs, duplicate_docs="fail")


    def test_write_with_duplicate_doc_ids_custom_index_skip(doc_store: BaseDocumentStore, duplicate_docs: List[Document]):
        doc_store.write_documents(duplicate_docs, index="custom", duplicate_docs="skip")
        assert len(doc_store.get_all_documents()) == 1


    def test_write_with_duplicate_doc_ids_custom_index_fail(doc_store: BaseDocumentStore, duplicate_docs: List[Document]):
        with pytest.raises(DuplicateDocumentError):
            doc_store.write_documents(duplicate_docs, index="custom", duplicate_docs="fail")

    
    def test_write_documents_id_hash_keys(doc_store: BaseDocumentStore, duplicate_docs_hash_key: List[Document]):
        doc_store.write_documents(duplicate_docs_hash_key)
        retrieved_docs = doc_store.get_all_documents()
        assert set(retrieved_docs) == duplicate_docs_hash_key


    def test_get_all_documents_without_filters(doc_store_with_docs: BaseDocumentStore, docs: List[Document]):
        retrieved_docs = doc_store_with_docs.get_all_documents()
        assert set(retrieved_docs) == set(docs)


    @pytest.mark.skipif(sys.platform in ["win32", "cygwin"], reason="Test fails on Windows with an SQLite exception")
    def test_get_all_documents_large_quantities(doc_store: BaseDocumentStore):  # https://github.com/deepset-ai/haystack/issues/1893
        docs_to_write = [
            Document(content=f"text_{i}", meta={"name": f"name_{i}"})
            for i in range(1000)
        ]
        doc_store.write_documents(docs_to_write)
        retrieved_docs = doc_store.get_all_documents()
        assert set(retrieved_docs) == set(docs_to_write)


    def test_get_all_documents_with_one_filters_one_result(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test2"]})
        assert len(retrieved_docs) == 1
        assert retrieved_docs[0].meta["name"] == "filename2"
        assert retrieved_docs[0].meta["meta_field"] == "test2"


    def test_get_all_documents_with_one_filters_many_results(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"odd_document": [True]})
        assert len(retrieved_docs) == 3
        assert {d.meta["name"] for d in retrieved_docs} == {"filename1", "filename3", "filename5"}
        assert {d.meta["meta_field"] for d in retrieved_docs} == {"test1", "test3", "test5"}
        

    def test_get_all_documents_with_many_filters_many_results(doc_store_with_docs: BaseDocumentStore):
        docs = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test1", "test3"]})
        assert len(docs) == 2
        assert {d.meta["name"] for d in docs} == {"filename1", "filename3"}
        assert {d.meta["meta_field"] for d in docs} == {"test1", "test3"}


    # def test_get_all_documents_with_correct_filters_legacy_sqlite(docs, tmp_path):
    #     doc_store_with_docs = get_doc_store("sql", tmp_path)
    #     doc_store_with_docs.write_documents(docs)

    #     doc_store_with_docs.use_windowed_query = False
    #     docs = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test2"]})
    #     assert len(docs) == 1
    #     assert docs[0].meta["name"] == "filename2"

    #     docs = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test1", "test3"]})
    #     assert len(docs) == 2
    #     assert {d.meta["name"] for d in docs} == {"filename1", "filename3"}
    #     assert {d.meta["meta_field"] for d in docs} == {"test1", "test3"}


    def test_get_all_documents_with_incorrect_filter_name(doc_store_with_docs: BaseDocumentStore):
        docs = doc_store_with_docs.get_all_documents(filters={"incorrect_meta_field": ["test2"]})
        assert len(docs) == 0


    def test_get_all_documents_with_incorrect_filter_value(doc_store_with_docs: BaseDocumentStore):
        docs = doc_store_with_docs.get_all_documents(filters={"meta_field": ["incorrect_value"]})
        assert len(docs) == 0


    def test_extended_filter_eq(doc_store_with_docs: BaseDocumentStore):
        eq_docs = doc_store_with_docs.get_all_documents(filters={"meta_field": {"$eq": "test1"}})
        normal_docs = doc_store_with_docs.get_all_documents(filters={"meta_field": "test1"})
        assert len(eq_docs) == 1
        assert len(normal_docs) == 1
        assert eq_docs == normal_docs


    def test_extended_filter_in(doc_store_with_docs: BaseDocumentStore):
        in_docs = doc_store_with_docs.get_all_documents(filters={"meta_field": {"$in": ["test1", "test2", "n.a."]}})
        normal_docs = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test1", "test2", "n.a."]})
        assert len(in_docs) == 2
        assert len(normal_docs) == 2
        assert in_docs == normal_docs


    def test_extended_filter_ne(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"meta_field": {"$ne": "test1"}})
        assert len(retrieved_docs) == 4
        assert "test1" not in {d.meta["meta_field"] for d in retrieved_docs}


    def test_extended_filter_nin(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"meta_field": {"$nin": ["test1", "test2", "n.a."]}})
        assert len(retrieved_docs) == 3
        assert {"test1", "test2"}.isdisjoint({d.meta["meta_field"] for d in retrieved_docs})
        

    def test_extended_filter_gt(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"numeric_field": {"$gt": 3.0}})
        assert len(retrieved_docs) == 3
        assert all(d.meta["numeric_field"] > 3.0 for d in retrieved_docs)


    def test_extended_filter_gte(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"numeric_field": {"$gte": 3.0}})
        assert len(retrieved_docs) == 4
        assert all(d.meta["numeric_field"] >= 3.0 for d in retrieved_docs)


    def test_extended_filter_lt(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"numeric_field": {"$lt": 3.0}})
        assert len(retrieved_docs) == 1
        assert all(d.meta["numeric_field"] < 3.0 for d in retrieved_docs)


    def test_extended_filter_lte(doc_store_with_docs: BaseDocumentStore):
        retrieved_docs = doc_store_with_docs.get_all_documents(filters={"numeric_field": {"$lte": 3.0}})
        assert len(retrieved_docs) == 2
        assert all(d.meta["numeric_field"] <= 3.0 for d in retrieved_docs)


    def test_extended_filter_compound_dates(doc_store_with_docs: BaseDocumentStore):
        filters = {"date_field": {"$lte": "2020-12-31", "$gte": "2019-01-01"}}
        start = datetime.strptime("2020-12-31", '%y-%m-%d').date()
        end = datetime.strptime("2019-01-01", '%y-%m-%d').date()

        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters)
        assert len(retrieved_docs) == 3
        assert all(start <= datetime.strptime(d.meta["date_field"], '%y-%m-%d').date() <= end for d in retrieved_docs)


    def test_extended_filter_compound_dates_and_other_field_explicit(doc_store_with_docs: BaseDocumentStore):
        filters = {
            "$and": {
                "date_field": {"$lte": "2020-12-31", "$gte": "2019-01-01"},
                "name": {"$in": ["filename5", "filename3"]},
            }
        }
        start = datetime.strptime("2020-12-31", '%y-%m-%d').date()
        end = datetime.strptime("2019-01-01", '%y-%m-%d').date()

        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters)
        assert len(retrieved_docs) == 1
        assert retrieved_docs[0].meta["name"] in ["filename5", "filename3"]
        assert start <= datetime.strptime(retrieved_docs[0].meta["date_field"], '%y-%m-%d').date() <= end


    def test_extended_filter_compound_dates_and_other_field_simplified(doc_store_with_docs: BaseDocumentStore):
        filters_simplified = {
            "date_field": {"$lte": "2020-12-31", "$gte": "2019-01-01"},
            "name": ["filename5", "filename3"],
        }
        start = datetime.strptime("2020-12-31", '%y-%m-%d').date()
        end = datetime.strptime("2019-01-01", '%y-%m-%d').date()
        
        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters_simplified)
        assert len(retrieved_docs) == 1
        assert retrieved_docs[0].meta["name"] in ["filename5", "filename3"]
        assert start <= datetime.strptime(retrieved_docs[0].meta["date_field"], '%y-%m-%d').date() <= end


    def test_extended_filter_compound_dates_and_or_explicit(doc_store_with_docs: BaseDocumentStore):
        filters = {
            "$and": {
                "date_field": {"$lte": "2020-12-31", "$gte": "2019-01-01"},
                "$or": {"name": {"$in": ["filename5", "filename3"]}, "numeric_field": {"$lte": 5.0}},
            }
        }
        start = datetime.strptime("2020-12-31", '%y-%m-%d').date()
        end = datetime.strptime("2019-01-01", '%y-%m-%d').date()

        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters)
        assert len(retrieved_docs) == 2
        assert retrieved_docs[0].meta["name"] in ["filename5", "filename3"] or retrieved_docs[0].meta["numeric_field"] <= 5.0
        assert start <= datetime.strptime(retrieved_docs[0].meta["date_field"], '%y-%m-%d').date() <= end


    def test_extended_filter_compound_dates_and_or_simplified(doc_store_with_docs: BaseDocumentStore):
        filters_simplified = {
            "date_field": {"$lte": "2020-12-31", "$gte": "2019-01-01"},
            "$or": {"name": ["filename5", "filename3"], "numeric_field": {"$lte": 5.0}},
        }
        start = datetime.strptime("2020-12-31", '%y-%m-%d').date()
        end = datetime.strptime("2019-01-01", '%y-%m-%d').date()

        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters_simplified)
        assert len(retrieved_docs) == 2
        assert retrieved_docs[0].meta["name"] in ["filename5", "filename3"] or retrieved_docs[0].meta["numeric_field"] <= 5.0
        assert start <= datetime.strptime(retrieved_docs[0].meta["date_field"], '%y-%m-%d').date() <= end


    def test_extended_filter_compound_dates_and_or_and_not_explicit(doc_store_with_docs: BaseDocumentStore):
        filters = {
            "$and": {
                "date_field": {"$lte": "2020-12-31", "$gte": "2019-01-01"},
                "$or": {
                    "name": {"$in": ["filename5", "filename3"]},
                    "$and": {"numeric_field": {"$lte": 5.0}, "$not": {"meta_field": {"$eq": "test2"}}},
                },
            }
        }
        start = datetime.strptime("2020-12-31", '%y-%m-%d').date()
        end = datetime.strptime("2019-01-01", '%y-%m-%d').date()

        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters)
        assert len(retrieved_docs) == 1
        assert (
            retrieved_docs[0].meta["name"] in ["filename5", "filename3"] or 
            (
                retrieved_docs[0].meta["numeric_field"] <= 5.0 and
                retrieved_docs[0].meta["meta_field"] != "test2"
            )
        )
        assert start <= datetime.strptime(retrieved_docs[0].meta["date_field"], '%y-%m-%d').date() <= end


    def test_extended_filter_compound_dates_and_or_and_not_simplified(doc_store_with_docs: BaseDocumentStore):
        filters_simplified = {
            "date_field": {"$lte": "2020-12-31", "$gte": "2019-01-01"},
            "$or": {
                "name": ["filename5", "filename3"],
                "$and": {"numeric_field": {"$lte": 5.0}, "$not": {"meta_field": "test2"}},
            },
        }
        start = datetime.strptime("2020-12-31", '%y-%m-%d').date()
        end = datetime.strptime("2019-01-01", '%y-%m-%d').date()

        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters_simplified)
        assert len(retrieved_docs) == 1
        assert (
            retrieved_docs[0].meta["name"] in ["filename5", "filename3"] or 
            (
                retrieved_docs[0].meta["numeric_field"] <= 5.0 and
                retrieved_docs[0].meta["meta_field"] != "test2"
            )
        )
        assert start <= datetime.strptime(retrieved_docs[0].meta["date_field"], '%y-%m-%d').date() <= end


    def test_extended_filter_compound_nested_not(doc_store_with_docs: BaseDocumentStore):
        # Test nested logical operations within "$not", important as we apply De Morgan's laws in Weaviatedocstore
        filters = {
            "$not": {
                "$or": {
                    "$and": {"numeric_field": {"$gt": 3.0}, "meta_field": {"$ne": "test3"}},
                    "$not": {"date_field": {"$lt": "2020-01-01"}},
                }
            }
        }

        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters)
        assert len(retrieved_docs) == 2
        assert {"test3", "test5"}.issubset({doc.meta["meta_field"] for doc in retrieved_docs})


    def test_extended_filter_compound_same_level_not(doc_store_with_docs: BaseDocumentStore):
        # Test same logical operator twice on same level, important as we apply De Morgan's laws in Weaviatedocstore
        filters = {
            "$or": [
                {"$and": {"meta_field": {"$in": ["test1", "test2"]}, "date_field": {"$gte": "2020-01-01"}}},
                {"$and": {"meta_field": {"$in": ["test3", "test4"]}, "date_field": {"$lt": "2020-01-01"}}},
            ]
        }
        retrieved_docs = doc_store_with_docs.get_all_documents(filters=filters)
        assert len(retrieved_docs) == 2
        assert {"test3", "test5"}.issubset({doc.meta["meta_field"] for doc in retrieved_docs})


    def test_get_document_by_id(doc_store: BaseDocumentStore, docs_with_ids: List[Document]):
        doc_store.write_documents(docs_with_ids)

        doc = doc_store.get_document_by_id(docs_with_ids[2].id)
        assert doc.id == docs_with_ids[2].id
        assert doc.content == docs_with_ids[2].content


    def test_get_documents_by_id(doc_store: BaseDocumentStore, docs_with_ids: List[Document]):
        # NOTE ES: Generate more docs than the elasticsearch default query size limit of 10 in the dedicated suite
        doc_store.write_documents(docs_with_ids)

        retrieved_by_id = doc_store.get_documents_by_id(docs_with_ids[1:4])
        assert set(doc.id for doc in retrieved_by_id) == set(docs_with_ids[1:4])


    def test_get_document_count(doc_store_with_docs: BaseDocumentStore, docs: List[Document]):
        assert doc_store_with_docs.get_document_count() == len(docs)


    def test_get_document_count_with_filters(doc_store_with_docs: BaseDocumentStore):
        assert doc_store_with_docs.get_document_count(filters={"odd_document": [False]}) == 2


    @pytest.mark.parametrize("batch_size", [1, 3])
    def test_get_all_documents_generator_batch(doc_store: BaseDocumentStore, batch_size: int):
        assert len(doc_store.get_all_documents_generator(batch_size=batch_size)) == batch_size 


    def test_get_all_documents_generator_batch_too_large(doc_store: BaseDocumentStore, docs: List[Document], batch_size: int):
        assert len(doc_store.get_all_documents_generator(batch_size=100)) == len(docs) 


    @pytest.mark.parametrize("batch_size", [0, -1, 0.5])
    def test_get_all_documents_generator_batch_too_small(doc_store: BaseDocumentStore, docs: List[Document], batch_size: int):
        assert not doc_store.get_all_documents_generator(batch_size=batch_size)


    @pytest.mark.parametrize("batch_size", [1, 3])
    def test_get_all_documents_generator_complete_list(doc_store: BaseDocumentStore, docs: List[Document], batch_size: int):
        assert len(list(doc_store.get_all_documents_generator(batch_size=batch_size))) == len(docs)


    @pytest.mark.parametrize("update_existing_docs", [True, False])
    def test_update_existing_docs(doc_store, update_existing_docs):
        original_docs = [{"content": "text1_orig", "id": "1", "meta_field_for_count": "a"}]

        updated_docs = [{"content": "text1_new", "id": "1", "meta_field_for_count": "a"}]

        doc_store.write_documents(original_docs)
        assert doc_store.get_document_count() == 1

        if update_existing_docs:
            doc_store.write_documents(updated_docs, duplicate_docs="overwrite")
        else:
            with pytest.raises(Exception):
                doc_store.write_documents(updated_docs, duplicate_docs="fail")

        stored_docs = doc_store.get_all_documents()
        assert len(stored_docs) == 1
        if update_existing_docs:
            assert stored_docs[0].content == updated_docs[0]["content"]
        else:
            assert stored_docs[0].content == original_docs[0]["content"]


    def test_write_document_meta(doc_store: BaseDocumentStore):
        docs = [
            {"content": "dict_without_meta", "id": "1"},
            {"content": "dict_with_meta", "meta_field": "test2", "name": "filename2", "id": "2"},
            Document(content="document_object_without_meta", id="3"),
            Document(content="document_object_with_meta", meta={"meta_field": "test4", "name": "filename3"}, id="4"),
        ]
        doc_store.write_documents(docs)
        docs_in_store = doc_store.get_all_documents()
        assert len(docs_in_store) == 4

        assert not doc_store.get_document_by_id("1").meta
        assert doc_store.get_document_by_id("2").meta["meta_field"] == "test2"
        assert not doc_store.get_document_by_id("3").meta
        assert doc_store.get_document_by_id("4").meta["meta_field"] == "test4"


    def test_write_document_index(doc_store: BaseDocumentStore):
        doc_store.delete_index("haystack_test_one")
        doc_store.delete_index("haystack_test_two")
        docs = [{"content": "text1", "id": "1"}, {"content": "text2", "id": "2"}]
        doc_store.write_documents([docs[0]], index="haystack_test_one")
        assert len(doc_store.get_all_documents(index="haystack_test_one")) == 1

        doc_store.write_documents([docs[1]], index="haystack_test_two")
        assert len(doc_store.get_all_documents(index="haystack_test_two")) == 1

        assert len(doc_store.get_all_documents(index="haystack_test_one")) == 1
        assert len(doc_store.get_all_documents()) == 0



    # FIXME this was not parametrized for Pinecone originally!!
    def test_document_with_embeddings(doc_store: BaseDocumentStore):
        docs = [
            {"content": "text1", "id": "1", "embedding": np.random.rand(768).astype(np.float32)},
            {"content": "text2", "id": "2", "embedding": np.random.rand(768).astype(np.float64)},
            {"content": "text3", "id": "3", "embedding": np.random.rand(768).astype(np.float32).tolist()},
            {"content": "text4", "id": "4", "embedding": np.random.rand(768).astype(np.float32)},
        ]
        doc_store.write_documents(docs)
        assert len(doc_store.get_all_documents()) == 4

        if not isinstance(doc_store, Weaviatedocstore):
            # weaviate is excluded because it would return dummy vectors instead of None
            docs_without_embedding = doc_store.get_all_documents(return_embedding=False)
            assert docs_without_embedding[0].embedding is None

        docs_with_embedding = doc_store.get_all_documents(return_embedding=True)
        assert isinstance(docs_with_embedding[0].embedding, (list, np.ndarray))


    # FIXME this was not parametrized for Pinecone originally!!
    @pytest.mark.parametrize("retriever", ["embedding"], indirect=True)
    def test_update_embeddings(doc_store, retriever):
        docs = []
        for i in range(6):
            docs.append({"content": f"text_{i}", "id": str(i), "meta_field": f"value_{i}"})
        docs.append({"content": "text_0", "id": "6", "meta_field": "value_0"})

        doc_store.write_documents(docs)
        doc_store.update_embeddings(retriever, batch_size=3)
        docs = doc_store.get_all_documents(return_embedding=True)
        assert len(docs) == 7
        for doc in docs:
            assert type(doc.embedding) is np.ndarray

        docs = doc_store.get_all_documents(filters={"meta_field": ["value_0"]}, return_embedding=True)
        assert len(docs) == 2
        for doc in docs:
            assert doc.meta["meta_field"] == "value_0"
        np.testing.assert_array_almost_equal(docs[0].embedding, docs[1].embedding, decimal=4)

        docs = doc_store.get_all_documents(filters={"meta_field": ["value_0", "value_5"]}, return_embedding=True)
        docs_with_value_0 = [doc for doc in docs if doc.meta["meta_field"] == "value_0"]
        docs_with_value_5 = [doc for doc in docs if doc.meta["meta_field"] == "value_5"]
        np.testing.assert_raises(
            AssertionError,
            np.testing.assert_array_equal,
            docs_with_value_0[0].embedding,
            docs_with_value_5[0].embedding,
        )

        doc = {
            "content": "text_7",
            "id": "7",
            "meta_field": "value_7",
            "embedding": retriever.embed_queries(texts=["a random string"])[0],
        }
        doc_store.write_documents([doc])

        docs = []
        for i in range(8, 11):
            docs.append({"content": f"text_{i}", "id": str(i), "meta_field": f"value_{i}"})
        doc_store.write_documents(docs)

        doc_before_update = doc_store.get_all_documents(filters={"meta_field": ["value_7"]})[0]
        embedding_before_update = doc_before_update.embedding

        # test updating only docs without embeddings
        if not isinstance(doc_store, Weaviatedocstore):
            # All the docs in Weaviate store have an embedding by default. "update_existing_embeddings=False" is not allowed
            doc_store.update_embeddings(retriever, batch_size=3, update_existing_embeddings=False)
            doc_after_update = doc_store.get_all_documents(filters={"meta_field": ["value_7"]})[0]
            embedding_after_update = doc_after_update.embedding
            np.testing.assert_array_equal(embedding_before_update, embedding_after_update)

        # test updating with filters
        if isinstance(doc_store, FAISSdocstore):
            with pytest.raises(Exception):
                doc_store.update_embeddings(
                    retriever, update_existing_embeddings=True, filters={"meta_field": ["value"]}
                )
        else:
            doc_store.update_embeddings(retriever, batch_size=3, filters={"meta_field": ["value_0", "value_1"]})
            doc_after_update = doc_store.get_all_documents(filters={"meta_field": ["value_7"]})[0]
            embedding_after_update = doc_after_update.embedding
            np.testing.assert_array_equal(embedding_before_update, embedding_after_update)

        # test update all embeddings
        doc_store.update_embeddings(retriever, batch_size=3, update_existing_embeddings=True)
        assert doc_store.get_embedding_count() == 11
        doc_after_update = doc_store.get_all_documents(filters={"meta_field": ["value_7"]})[0]
        embedding_after_update = doc_after_update.embedding
        np.testing.assert_raises(
            AssertionError, np.testing.assert_array_equal, embedding_before_update, embedding_after_update
        )

        # test update embeddings for newly added docs
        docs = []
        for i in range(12, 15):
            docs.append({"content": f"text_{i}", "id": str(i), "meta_field": f"value_{i}"})
        doc_store.write_documents(docs)

        if not isinstance(doc_store, Weaviatedocstore):
            # All the docs in Weaviate store have an embedding by default. "update_existing_embeddings=False" is not allowed
            doc_store.update_embeddings(retriever, batch_size=3, update_existing_embeddings=False)
            assert doc_store.get_embedding_count() == 14



    def test_delete_all_docs(doc_store_with_docs):
        assert len(doc_store_with_docs.get_all_documents()) == 5

        doc_store_with_docs.delete_docs()
        docs = doc_store_with_docs.get_all_documents()
        assert len(docs) == 0


    def test_delete_docs(doc_store_with_docs):
        assert len(doc_store_with_docs.get_all_documents()) == 5

        doc_store_with_docs.delete_docs()
        docs = doc_store_with_docs.get_all_documents()
        assert len(docs) == 0


    def test_delete_docs_with_filters(doc_store_with_docs):
        doc_store_with_docs.delete_docs(filters={"meta_field": ["test1", "test2", "test4", "test5"]})
        docs = doc_store_with_docs.get_all_documents()
        assert len(docs) == 1
        assert docs[0].meta["meta_field"] == "test3"


    def test_delete_docs_by_id(doc_store_with_docs):
        import logging

        logging.info(len(doc_store_with_docs.get_all_documents()))
        docs_to_delete = doc_store_with_docs.get_all_documents(
            filters={"meta_field": ["test1", "test2", "test4", "test5"]}
        )
        logging.info(len(docs_to_delete))
        docs_not_to_delete = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test3"]})
        logging.info(len(docs_not_to_delete))

        doc_store_with_docs.delete_docs(ids=[doc.id for doc in docs_to_delete])
        all_docs_left = doc_store_with_docs.get_all_documents()
        assert len(all_docs_left) == 1
        assert all_docs_left[0].meta["meta_field"] == "test3"

        all_ids_left = [doc.id for doc in all_docs_left]
        assert all(doc.id in all_ids_left for doc in docs_not_to_delete)


    def test_delete_docs_by_id_with_filters(doc_store_with_docs):
        docs_to_delete = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test1", "test2"]})
        docs_not_to_delete = doc_store_with_docs.get_all_documents(filters={"meta_field": ["test3"]})

        doc_store_with_docs.delete_docs(ids=[doc.id for doc in docs_to_delete], filters={"meta_field": ["test1"]})

        all_docs_left = doc_store_with_docs.get_all_documents()
        assert len(all_docs_left) == 4
        assert all(doc.meta["meta_field"] != "test1" for doc in all_docs_left)

        all_ids_left = [doc.id for doc in all_docs_left]
        assert all(doc.id in all_ids_left for doc in docs_not_to_delete)










    def test_labels(doc_store: BaseDocumentStore):
        label = Label(
            query="question1",
            answer=Answer(
                answer="answer",
                type="extractive",
                score=0.0,
                context="something",
                offsets_in_document=[Span(start=12, end=14)],
                offsets_in_context=[Span(start=12, end=14)],
            ),
            is_correct_answer=True,
            is_correct_document=True,
            document=Document(content="something", id="123"),
            no_answer=False,
            origin="gold-label",
        )
        doc_store.write_labels([label])
        labels = doc_store.get_all_labels()
        assert len(labels) == 1
        assert label == labels[0]

        # different index
        doc_store.write_labels([label], index="another_index")
        labels = doc_store.get_all_labels(index="another_index")
        assert len(labels) == 1
        doc_store.delete_labels(index="another_index")
        labels = doc_store.get_all_labels(index="another_index")
        assert len(labels) == 0
        labels = doc_store.get_all_labels()
        assert len(labels) == 1

        # write second label + duplicate
        label2 = Label(
            query="question2",
            answer=Answer(
                answer="another answer",
                type="extractive",
                score=0.0,
                context="something",
                offsets_in_document=[Span(start=12, end=14)],
                offsets_in_context=[Span(start=12, end=14)],
            ),
            is_correct_answer=True,
            is_correct_document=True,
            document=Document(content="something", id="324"),
            no_answer=False,
            origin="gold-label",
        )
        doc_store.write_labels([label, label2])
        labels = doc_store.get_all_labels()

        # check that second label has been added but not the duplicate
        assert len(labels) == 2
        assert label in labels
        assert label2 in labels

        # delete filtered label2 by id
        doc_store.delete_labels(ids=[labels[1].id])
        labels = doc_store.get_all_labels()
        assert label == labels[0]
        assert len(labels) == 1

        # re-add label2
        doc_store.write_labels([label2])
        labels = doc_store.get_all_labels()
        assert len(labels) == 2

        # delete filtered label2 by query text
        doc_store.delete_labels(filters={"query": [labels[1].query]})
        labels = doc_store.get_all_labels()
        assert label == labels[0]
        assert len(labels) == 1

        # re-add label2
        doc_store.write_labels([label2])
        labels = doc_store.get_all_labels()
        assert len(labels) == 2

        # delete intersection of filters and ids, which is empty
        doc_store.delete_labels(ids=[labels[0].id], filters={"query": [labels[1].query]})
        labels = doc_store.get_all_labels()
        assert len(labels) == 2
        assert label in labels
        assert label2 in labels

        # delete all labels
        doc_store.delete_labels()
        labels = doc_store.get_all_labels()
        assert len(labels) == 0



    def test_multilabel(doc_store: BaseDocumentStore):
        labels = [
            Label(
                id="standard",
                query="question",
                answer=Answer(answer="answer1", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
            ),
            # different answer in same doc
            Label(
                id="diff-answer-same-doc",
                query="question",
                answer=Answer(answer="answer2", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
            ),
            # answer in different doc
            Label(
                id="diff-answer-diff-doc",
                query="question",
                answer=Answer(answer="answer3", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some other", id="333"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
            ),
            # 'no answer', should be excluded from MultiLabel
            Label(
                id="4-no-answer",
                query="question",
                answer=Answer(answer="", offsets_in_document=[Span(start=0, end=0)]),
                document=Document(content="some", id="777"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=True,
                origin="gold-label",
            ),
            # is_correct_answer=False, should be excluded from MultiLabel if "drop_negatives = True"
            Label(
                id="5-negative",
                query="question",
                answer=Answer(answer="answer5", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=False,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
            ),
        ]
        doc_store.write_labels(labels)
        # regular labels - not aggregated
        list_labels = doc_store.get_all_labels()
        assert list_labels == labels
        assert len(list_labels) == 5

        # Currently we don't enforce writing (missing) docs automatically when adding labels and there's no DB relationship between the two.
        # We should introduce this when we refactored the logic of "index" to be rather a "collection" of labels+docs
        # docs = doc_store.get_all_documents()
        # assert len(docs) == 3

        # Multi labels (open domain)
        multi_labels_open = doc_store.get_all_labels_aggregated(open_domain=True, drop_negative_labels=True)

        # for open-domain we group all together as long as they have the same question
        assert len(multi_labels_open) == 1
        # all labels are in there except the negative one and the no_answer
        assert len(multi_labels_open[0].labels) == 4
        assert len(multi_labels_open[0].answers) == 3
        assert "5-negative" not in [l.id for l in multi_labels_open[0].labels]
        assert len(multi_labels_open[0].document_ids) == 3

        # Don't drop the negative label
        multi_labels_open = doc_store.get_all_labels_aggregated(
            open_domain=True, drop_no_answers=False, drop_negative_labels=False
        )
        assert len(multi_labels_open[0].labels) == 5
        assert len(multi_labels_open[0].answers) == 4
        assert len(multi_labels_open[0].document_ids) == 4

        # Drop no answer + negative
        multi_labels_open = doc_store.get_all_labels_aggregated(
            open_domain=True, drop_no_answers=True, drop_negative_labels=True
        )
        assert len(multi_labels_open[0].labels) == 3
        assert len(multi_labels_open[0].answers) == 3
        assert len(multi_labels_open[0].document_ids) == 3

        # for closed domain we group by document so we expect 3 multilabels with 2,1,1 labels each (negative dropped again)
        multi_labels = doc_store.get_all_labels_aggregated(open_domain=False, drop_negative_labels=True)
        assert len(multi_labels) == 3
        label_counts = set([len(ml.labels) for ml in multi_labels])
        assert label_counts == set([2, 1, 1])

        assert len(multi_labels[0].answers) == len(multi_labels[0].document_ids)



    def test_multilabel_no_answer(doc_store: BaseDocumentStore):
        labels = [
            Label(
                query="question",
                answer=Answer(answer=""),
                is_correct_answer=True,
                is_correct_document=True,
                document=Document(content="some", id="777"),
                no_answer=True,
                origin="gold-label",
            ),
            # no answer in different doc
            Label(
                query="question",
                answer=Answer(answer=""),
                is_correct_answer=True,
                is_correct_document=True,
                document=Document(content="some", id="123"),
                no_answer=True,
                origin="gold-label",
            ),
            # no answer in same doc, should be excluded
            Label(
                query="question",
                answer=Answer(answer=""),
                is_correct_answer=True,
                is_correct_document=True,
                document=Document(content="some", id="777"),
                no_answer=True,
                origin="gold-label",
            ),
            # no answer with is_correct_answer=False, should be excluded
            Label(
                query="question",
                answer=Answer(answer=""),
                is_correct_answer=False,
                is_correct_document=True,
                document=Document(content="some", id="777"),
                no_answer=True,
                origin="gold-label",
            ),
        ]

        doc_store.write_labels(labels)

        labels = doc_store.get_all_labels()
        assert len(labels) == 4

        multi_labels = doc_store.get_all_labels_aggregated(
            open_domain=True, drop_no_answers=False, drop_negative_labels=True
        )
        assert len(multi_labels) == 1
        assert multi_labels[0].no_answer == True
        assert len(multi_labels[0].document_ids) == 0
        assert len(multi_labels[0].answers) == 1

        multi_labels = doc_store.get_all_labels_aggregated(
            open_domain=True, drop_no_answers=False, drop_negative_labels=False
        )
        assert len(multi_labels) == 1
        assert multi_labels[0].no_answer == True
        assert len(multi_labels[0].document_ids) == 0
        assert len(multi_labels[0].labels) == 3
        assert len(multi_labels[0].answers) == 1


    # exclude weaviate because it does not support storing labels
    # exclude faiss and milvus as label metadata is not implemented
    def test_multilabel_filter_aggregations(doc_store: BaseDocumentStore):
        labels = [
            Label(
                id="standard",
                query="question",
                answer=Answer(answer="answer1", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                filters={"name": ["123"]},
            ),
            # different answer in same doc
            Label(
                id="diff-answer-same-doc",
                query="question",
                answer=Answer(answer="answer2", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                filters={"name": ["123"]},
            ),
            # answer in different doc
            Label(
                id="diff-answer-diff-doc",
                query="question",
                answer=Answer(answer="answer3", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some other", id="333"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                filters={"name": ["333"]},
            ),
            # 'no answer', should be excluded from MultiLabel
            Label(
                id="4-no-answer",
                query="question",
                answer=Answer(answer="", offsets_in_document=[Span(start=0, end=0)]),
                document=Document(content="some", id="777"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=True,
                origin="gold-label",
                filters={"name": ["777"]},
            ),
            # is_correct_answer=False, should be excluded from MultiLabel if "drop_negatives = True"
            Label(
                id="5-negative",
                query="question",
                answer=Answer(answer="answer5", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=False,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                filters={"name": ["123"]},
            ),
        ]
        doc_store.write_labels(labels)
        # regular labels - not aggregated
        list_labels = doc_store.get_all_labels()
        assert list_labels == labels
        assert len(list_labels) == 5

        # Multi labels (open domain)
        multi_labels_open = doc_store.get_all_labels_aggregated(open_domain=True, drop_negative_labels=True)

        # for open-domain we group all together as long as they have the same question and filters
        assert len(multi_labels_open) == 3
        label_counts = set([len(ml.labels) for ml in multi_labels_open])
        assert label_counts == set([2, 1, 1])
        # all labels are in there except the negative one and the no_answer
        assert "5-negative" not in [l.id for multi_label in multi_labels_open for l in multi_label.labels]

        assert len(multi_labels_open[0].answers) == len(multi_labels_open[0].document_ids)

        # for closed domain we group by document so we expect the same as with filters
        multi_labels = doc_store.get_all_labels_aggregated(open_domain=False, drop_negative_labels=True)
        assert len(multi_labels) == 3
        label_counts = set([len(ml.labels) for ml in multi_labels])
        assert label_counts == set([2, 1, 1])

        assert len(multi_labels[0].answers) == len(multi_labels[0].document_ids)


    # exclude weaviate because it does not support storing labels
    # exclude faiss and milvus as label metadata is not implemented
    def test_multilabel_meta_aggregations(doc_store: BaseDocumentStore):
        labels = [
            Label(
                id="standard",
                query="question",
                answer=Answer(answer="answer1", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                meta={"file_id": ["123"]},
            ),
            # different answer in same doc
            Label(
                id="diff-answer-same-doc",
                query="question",
                answer=Answer(answer="answer2", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                meta={"file_id": ["123"]},
            ),
            # answer in different doc
            Label(
                id="diff-answer-diff-doc",
                query="question",
                answer=Answer(answer="answer3", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some other", id="333"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                meta={"file_id": ["333"]},
            ),
            # 'no answer', should be excluded from MultiLabel
            Label(
                id="4-no-answer",
                query="question",
                answer=Answer(answer="", offsets_in_document=[Span(start=0, end=0)]),
                document=Document(content="some", id="777"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=True,
                origin="gold-label",
                meta={"file_id": ["777"]},
            ),
            # is_correct_answer=False, should be excluded from MultiLabel if "drop_negatives = True"
            Label(
                id="5-888",
                query="question",
                answer=Answer(answer="answer5", offsets_in_document=[Span(start=12, end=18)]),
                document=Document(content="some", id="123"),
                is_correct_answer=True,
                is_correct_document=True,
                no_answer=False,
                origin="gold-label",
                meta={"file_id": ["888"]},
            ),
        ]
        doc_store.write_labels(labels)
        # regular labels - not aggregated
        list_labels = doc_store.get_all_labels()
        assert list_labels == labels
        assert len(list_labels) == 5

        # Multi labels (open domain)
        multi_labels_open = doc_store.get_all_labels_aggregated(open_domain=True, drop_negative_labels=True)

        # for open-domain we group all together as long as they have the same question and filters
        assert len(multi_labels_open) == 1
        assert len(multi_labels_open[0].labels) == 5

        multi_labels = doc_store.get_all_labels_aggregated(
            open_domain=True, drop_negative_labels=True, aggregate_by_meta="file_id"
        )
        assert len(multi_labels) == 4
        label_counts = set([len(ml.labels) for ml in multi_labels])
        assert label_counts == set([2, 1, 1, 1])
        for multi_label in multi_labels:
            for l in multi_label.labels:
                assert l.filters == l.meta
                assert multi_label.filters == l.filters








    def test_update_meta(doc_store: BaseDocumentStore):
        docs = [
            Document(content="Doc1", meta={"meta_key_1": "1", "meta_key_2": "1"}),
            Document(content="Doc2", meta={"meta_key_1": "2", "meta_key_2": "2"}),
            Document(content="Doc3", meta={"meta_key_1": "3", "meta_key_2": "3"}),
        ]
        doc_store.write_documents(docs)
        document_2 = doc_store.get_all_documents(filters={"meta_key_2": ["2"]})[0]
        doc_store.update_document_meta(document_2.id, meta={"meta_key_1": "99", "meta_key_2": "2"})
        updated_document = doc_store.get_document_by_id(document_2.id)
        assert len(updated_document.meta.keys()) == 2
        assert updated_document.meta["meta_key_1"] == "99"
        assert updated_document.meta["meta_key_2"] == "2"










    @pytest.mark.parametrize("doc_store_type", ["elasticsearch", "memory"])
    def test_custom_embedding_field(doc_store_type, tmp_path):
        doc_store = get_doc_store(
            doc_store_type=doc_store_type,
            tmp_path=tmp_path,
            embedding_field="custom_embedding_field",
            index="custom_embedding_field",
        )
        doc_to_write = {"content": "test", "custom_embedding_field": np.random.rand(768).astype(np.float32)}
        doc_store.write_documents([doc_to_write])
        docs = doc_store.get_all_documents(return_embedding=True)
        assert len(docs) == 1
        assert docs[0].content == "test"
        np.testing.assert_array_equal(doc_to_write["custom_embedding_field"], docs[0].embedding)








    # FIXME Originally not parametrized for Pinecone!
    @pytest.mark.embedding_dim(384)
    def test_similarity_score_sentence_transformers(doc_store_with_docs):
        retriever = EmbeddingRetriever(
            doc_store=doc_store_with_docs, embedding_model="sentence-transformers/paraphrase-MiniLM-L3-v2"
        )
        doc_store_with_docs.update_embeddings(retriever)
        pipeline = docsearchPipeline(retriever)
        prediction = pipeline.run("Paul lives in New York")
        scores = [document.score for document in prediction["docs"]]
        assert scores == pytest.approx(
            [0.8497486114501953, 0.6622999012470245, 0.6077829301357269, 0.5928314849734306, 0.5614184625446796], abs=1e-3
        )


    # FIXME Originally not parametrized for Pinecone!
    @pytest.mark.embedding_dim(384)
    def test_similarity_score(doc_store_with_docs):
        retriever = EmbeddingRetriever(
            doc_store=doc_store_with_docs,
            embedding_model="sentence-transformers/paraphrase-MiniLM-L3-v2",
            model_format="farm",
        )
        doc_store_with_docs.update_embeddings(retriever)
        pipeline = docsearchPipeline(retriever)
        prediction = pipeline.run("Paul lives in New York")
        scores = [document.score for document in prediction["docs"]]
        assert scores == pytest.approx(
            [0.9102507941407827, 0.6937791467877008, 0.6491682889305038, 0.6321622491318529, 0.5909129441370939], abs=1e-3
        )


    # FIXME Originally not parametrized for Pinecone!
    @pytest.mark.embedding_dim(384)
    def test_similarity_score_without_scaling(doc_store_with_docs):
        retriever = EmbeddingRetriever(
            doc_store=doc_store_with_docs,
            embedding_model="sentence-transformers/paraphrase-MiniLM-L3-v2",
            scale_score=False,
            model_format="farm",
        )
        doc_store_with_docs.update_embeddings(retriever)
        pipeline = docsearchPipeline(retriever)
        prediction = pipeline.run("Paul lives in New York")
        scores = [document.score for document in prediction["docs"]]
        assert scores == pytest.approx(
            [0.8205015882815654, 0.3875582935754016, 0.29833657786100765, 0.26432449826370585, 0.18182588827418789],
            abs=1e-3,
        )


    # FIXME Originally not parametrized for Pinecone!
    @pytest.mark.embedding_dim(384)
    def test_similarity_score_dot_product(doc_store_dot_product_with_docs):
        retriever = EmbeddingRetriever(
            doc_store=doc_store_dot_product_with_docs,
            embedding_model="sentence-transformers/paraphrase-MiniLM-L3-v2",
            model_format="farm",
        )
        doc_store_dot_product_with_docs.update_embeddings(retriever)
        pipeline = docsearchPipeline(retriever)
        prediction = pipeline.run("Paul lives in New York")
        scores = [document.score for document in prediction["docs"]]
        assert scores == pytest.approx(
            [0.5526494403409358, 0.5247784342375555, 0.5189836829440964, 0.5179697273254912, 0.5112024928228626], abs=1e-3
        )


    # FIXME Originally not parametrized for Pinecone!
    @pytest.mark.embedding_dim(384)
    def test_similarity_score_dot_product_without_scaling(doc_store_dot_product_with_docs):
        retriever = EmbeddingRetriever(
            doc_store=doc_store_dot_product_with_docs,
            embedding_model="sentence-transformers/paraphrase-MiniLM-L3-v2",
            scale_score=False,
            model_format="farm",
        )
        doc_store_dot_product_with_docs.update_embeddings(retriever)
        pipeline = docsearchPipeline(retriever)
        prediction = pipeline.run("Paul lives in New York")
        scores = [document.score for document in prediction["docs"]]
        assert scores == pytest.approx(
            [21.13810000000001, 9.919499999999971, 7.597099999999955, 7.191000000000031, 4.481750000000034], abs=1e-3
        )


    def test_custom_headers(doc_store_with_docs: BaseDocumentStore):
        mock_client = None
        if isinstance(doc_store_with_docs, Elasticsearchdocstore):
            es_doc_store: Elasticsearchdocstore = doc_store_with_docs
            mock_client = Mock(wraps=es_doc_store.client)
            es_doc_store.client = mock_client
        custom_headers = {"X-My-Custom-Header": "header-value"}
        if not mock_client:
            with pytest.raises(NotImplementedError):
                docs = doc_store_with_docs.get_all_documents(headers=custom_headers)
        else:
            docs = doc_store_with_docs.get_all_documents(headers=custom_headers)
            mock_client.search.assert_called_once()
            args, kwargs = mock_client.search.call_args
            assert "headers" in kwargs
            assert kwargs["headers"] == custom_headers
            assert len(docs) > 0











class TestPineconedocstore:

    # Fixtures

    @pytest.fixture
    def MockedOpenSearchdocstore(self, monkeypatch):
        """
        The fixture provides an OpenSearchdocstore
        equipped with a mocked client
        """
        klass = OpenSearchdocstore
        monkeypatch.setattr(klass, "_init_client", MagicMock())
        return klass

    @pytest.fixture
    def doc_store(self):
        """
        This fixture provides a working document store and takes care of removing the indices when done
        """
        # index_name = __name__
        # labels_index_name = f"{index_name}_labels"
        # ds = OpenSearchdocstore(index=index_name, label_index=labels_index_name, port=9201, create_index=True)
        # yield ds
        # ds.delete_index(index_name)
        # ds.delete_index(labels_index_name)

    @pytest.fixture
    def docs(self):
        docs = [
            {
                "meta": {"name": "name_1", "year": "2020", "month": "01"},
                "content": "text_1",
                "embedding": np.random.rand(768).astype(np.float32),
            },
            {
                "meta": {"name": "name_2", "year": "2020", "month": "02"},
                "content": "text_2",
                "embedding": np.random.rand(768).astype(np.float32),
            },
            {
                "meta": {"name": "name_3", "year": "2020", "month": "03"},
                "content": "text_3",
                "embedding": np.random.rand(768).astype(np.float64),
            },
            {
                "meta": {"name": "name_4", "year": "2021", "month": "01"},
                "content": "text_4",
                "embedding": np.random.rand(768).astype(np.float32),
            },
            {
                "meta": {"name": "name_5", "year": "2021", "month": "02"},
                "content": "text_5",
                "embedding": np.random.rand(768).astype(np.float32),
            },
            {
                "meta": {"name": "name_6", "year": "2021", "month": "03"},
                "content": "text_6",
                "embedding": np.random.rand(768).astype(np.float64),
            },
        ]
        return docs

    # Integration tests

    @pytest.mark.integration
    def test___init__(self):
        OpenSearchdocstore(index="default_index", port=9201, create_index=True)

    

    # Unit tests

    def test___init__api_key_raises_warning(self, MockedOpenSearchdocstore):
        with pytest.warns(UserWarning):
            MockedOpenSearchdocstore(api_key="foo")
            MockedOpenSearchdocstore(api_key_id="bar")
            MockedOpenSearchdocstore(api_key="foo", api_key_id="bar")

    