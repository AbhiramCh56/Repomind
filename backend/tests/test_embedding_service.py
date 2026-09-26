import unittest
import uuid
from unittest import mock

from app.models.chunk import Chunk
from app.models.file import File
from app.services import embedding_service, rag_service
from support import FakeChromaClient, FakeEmbedder, FakeSession, make_repository


def _rows(count: int):
    rows = []
    for index in range(count):
        file = File(id=uuid.uuid4(), file_path=f"src/mod{index}.py", language="Python")
        chunk = Chunk(
            id=uuid.uuid4(),
            chunk_type="function",
            name=f"fn_{index}",
            content=f"def fn_{index}():\n    return {index}\n",
            start_line=1,
            end_line=2,
        )
        rows.append((chunk, file))
    return rows


class CollectionNamingTest(unittest.TestCase):
    def test_collection_name_is_canonical(self):
        self.assertEqual(
            embedding_service.get_collection_name("d5d87f22-c430-4379-a237-72455ed735fd"),
            "repo_d5d87f22c4304379a23772455ed735fd",
        )

    def test_rag_service_shares_the_single_implementation(self):
        self.assertIs(rag_service.get_collection_name, embedding_service.get_collection_name)


class DeleteCollectionTest(unittest.TestCase):
    def test_delete_removes_the_collection(self):
        client = FakeChromaClient()
        client.get_or_create_collection(name="repo_abc")

        with mock.patch.object(embedding_service, "get_chroma_client", return_value=client):
            removed = embedding_service.delete_repository_collection("abc")

        self.assertTrue(removed)
        self.assertEqual(client.deleted, ["repo_abc"])
        self.assertEqual(client.collections, {})

    def test_delete_is_idempotent(self):
        client = FakeChromaClient()

        with mock.patch.object(embedding_service, "get_chroma_client", return_value=client):
            self.assertFalse(embedding_service.delete_repository_collection("abc"))
            self.assertFalse(embedding_service.delete_repository_collection("abc"))


class EmbeddingResultTest(unittest.TestCase):
    def test_complete_requires_every_chunk(self):
        self.assertTrue(embedding_service.EmbeddingResult(total=3, embedded=3).complete)
        self.assertFalse(embedding_service.EmbeddingResult(total=3, embedded=2).complete)
        self.assertIn("3/3", embedding_service.EmbeddingResult(total=3, embedded=3).summary())


class EmbedRepositoryChunksTest(unittest.TestCase):
    def _run(self, rows, client=None, embedder=None):
        client = client or FakeChromaClient()
        embedder = embedder or FakeEmbedder()
        repo = make_repository()
        db = FakeSession(repo, rows=rows)
        with mock.patch.object(embedding_service, "get_chroma_client", return_value=client), \
             mock.patch.object(embedding_service, "get_embedding_function", return_value=embedder):
            result = embedding_service.embed_repository_chunks(str(repo.id), db)
        return result, client, embedder

    def test_successful_run_embeds_every_chunk(self):
        result, client, _ = self._run(_rows(3))

        self.assertTrue(result.complete)
        self.assertEqual(result.embedded, 3)
        self.assertEqual(result.errors, [])
        collection = list(client.collections.values())[0]
        self.assertEqual(len(collection.documents), 3)
        self.assertIn("File: src/mod0.py", collection.documents[0])

    def test_metadata_is_attached_to_every_vector(self):
        _, client, _ = self._run(_rows(2))

        collection = list(client.collections.values())[0]
        for metadata in collection.metadatas:
            self.assertEqual(
                set(metadata),
                {"file_path", "language", "chunk_type", "name", "start_line"},
            )

    def test_reprocessing_does_not_duplicate_vectors(self):
        rows = _rows(3)
        repo_id = str(make_repository().id)

        client = FakeChromaClient()
        for _ in range(3):
            repo = make_repository(id=uuid.UUID(repo_id))
            db = FakeSession(repo, rows=rows)
            with mock.patch.object(embedding_service, "get_chroma_client", return_value=client), \
                 mock.patch.object(embedding_service, "get_embedding_function", return_value=FakeEmbedder()):
                embedding_service.embed_repository_chunks(repo_id, db)

        collection = list(client.collections.values())[0]
        self.assertEqual(len(collection.ids), 3)
        self.assertEqual(len(set(collection.ids)), 3)
        collection_name = f"repo_{repo_id.replace('-', '')}"
        self.assertEqual(client.deleted, [collection_name, collection_name])

    def test_transient_batch_failure_is_retried(self):
        embedder = FakeEmbedder(fail_on_call=1)
        with mock.patch.object(embedding_service.settings, "EMBEDDING_BATCH_SIZE", 10):
            result, _, _ = self._run(_rows(2), embedder=embedder)

        self.assertTrue(result.complete)
        self.assertEqual(result.embedded, 2)
        self.assertEqual(embedder.calls, 2)

    def test_permanent_failure_fails_the_run(self):
        class AlwaysFails(FakeEmbedder):
            def embed_documents(self, documents):
                raise RuntimeError("model exploded")

        with mock.patch.object(embedding_service.settings, "EMBEDDING_BATCH_SIZE", 10):
            result, _, _ = self._run(_rows(2), embedder=AlwaysFails())

        self.assertFalse(result.complete)
        self.assertEqual(result.embedded, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("model exploded", result.errors[0])

    def test_repository_without_chunks_raises(self):
        with self.assertRaises(ValueError):
            self._run([])

    def test_unknown_repository_raises(self):
        db = FakeSession(None, rows=[])
        with mock.patch.object(embedding_service, "get_chroma_client", return_value=FakeChromaClient()):
            with self.assertRaises(ValueError):
                embedding_service.embed_repository_chunks(str(uuid.uuid4()), db)

    def test_batches_respect_the_configured_size(self):
        with mock.patch.object(embedding_service.settings, "EMBEDDING_BATCH_SIZE", 2):
            _, client, embedder = self._run(_rows(5))

        self.assertEqual(embedder.calls, 3)
        self.assertEqual(len(list(client.collections.values())[0].ids), 5)


if __name__ == "__main__":
    unittest.main()
