import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from pydantic import ValidationError

from service.api import export, stream, synthesize
from service.core.chunking import chunk_text
from service.core.config import config
from service.core.jobs import JobRegistry
from service.core.models import ExportRequest, StreamChunkingConfig, StreamRequest, SynthesizeRequest


DOCUMENT = ' '.join(f'Word{index}' for index in range(9000))


class ChunkingTests(unittest.TestCase):
    def test_long_sentence_preserves_every_word_in_order(self):
        chunks = chunk_text(DOCUMENT)
        self.assertEqual(' '.join(chunks), DOCUMENT)
        self.assertTrue(all(0 < len(chunk) <= 1000 for chunk in chunks))

    def test_long_unbroken_text_preserves_every_character(self):
        text = 'abcdefghij' * 6000
        chunks = chunk_text(text)
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))

    def test_target_larger_than_maximum_still_respects_limit(self):
        text = 'A sentence. ' * 100
        chunks = chunk_text(text, target_chars=500, max_chars=30)
        self.assertEqual(' '.join(chunks), text.strip())
        self.assertTrue(all(len(chunk) <= 30 for chunk in chunks))

    def test_chunker_rejects_nonpositive_limits(self):
        for limit in (0, -1):
            with self.assertRaises(ValueError):
                chunk_text(DOCUMENT, max_chars=limit)

    def test_chunk_sizes_must_be_positive(self):
        for field in ('target_chars', 'max_chars'):
            for value in (0, -1):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        StreamChunkingConfig(**{field: value})


class DocumentApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_document_streams_all_chunks_in_order(self):
        registry = JobRegistry()
        spoken = []
        provider = mock.Mock()
        provider.synthesize.side_effect = lambda text, *_: spoken.append(text) or text.encode()
        with tempfile.TemporaryDirectory() as output, \
                mock.patch.object(config, 'output_dir', Path(output)), \
                mock.patch.object(stream, 'registry', registry), \
                mock.patch.object(stream, '_get_provider', return_value=provider), \
                mock.patch.object(stream, 'local_voice_paths'), \
                mock.patch.object(stream, 'get_cached', return_value=None), \
                mock.patch.object(stream, 'put_cached'):
            result = await stream.stream(StreamRequest(text=DOCUMENT))
            job = registry.get(result.job_id)
            self.assertTrue(await asyncio.to_thread(job.wait, 5))
            self.assertIsNone(job.snapshot()['error'])
            self.assertGreater(len(result.chunks), 1)
            audio = []
            for index, chunk in enumerate(result.chunks):
                self.assertEqual(chunk.index, index)
                response = await stream.get_chunk_audio(result.job_id, f'{index}.mp3')
                audio.append(response.body.decode())
            self.assertEqual(' '.join(audio), DOCUMENT)
            self.assertEqual(audio, spoken)
            self.assertTrue(all(len(text) <= 1000 for text in spoken))

    async def test_first_chunk_available_before_completion_and_job_can_stop(self):
        registry = JobRegistry()
        second_started = threading.Event()
        release = threading.Event()
        worker_done = threading.Event()
        provider = mock.Mock()

        def speak(text, *_):
            if provider.synthesize.call_count == 2:
                second_started.set()
                release.wait(5)
            return text.encode()

        provider.synthesize.side_effect = speak
        original_worker = stream._synthesize_chunks

        def worker(**kwargs):
            try:
                original_worker(**kwargs)
            finally:
                worker_done.set()

        with tempfile.TemporaryDirectory() as output, \
                mock.patch.object(config, 'output_dir', Path(output)), \
                mock.patch.object(config, 'max_input_length', 100), \
                mock.patch.object(stream, 'registry', registry), \
                mock.patch.object(stream, '_get_provider', return_value=provider), \
                mock.patch.object(stream, 'local_voice_paths'), \
                mock.patch.object(stream, '_synthesize_chunks', side_effect=worker), \
                mock.patch.object(stream, 'get_cached', return_value=None), \
                mock.patch.object(stream, 'put_cached'):
            try:
                result = await stream.stream(StreamRequest(text=DOCUMENT))
                self.assertTrue(await asyncio.to_thread(second_started.wait, 5))
                job = registry.get(result.job_id)
                self.assertFalse(job.snapshot()['complete'])
                first = await stream.get_chunk_audio(result.job_id, '0.mp3')
                self.assertTrue(first.body)
                self.assertLessEqual(len(first.body), 100)
                self.assertTrue(registry.cancel(result.job_id))
            finally:
                release.set()
                if second_started.is_set():
                    self.assertTrue(await asyncio.to_thread(worker_done.wait, 5))
            self.assertEqual(provider.synthesize.call_count, 2)
            self.assertFalse((Path(output) / result.job_id / '1.mp3').exists())

    async def test_large_document_exports_all_text_with_bounded_calls(self):
        spoken = []

        def speak(text, *_):
            spoken.append(text)
            return text.encode()

        def concatenate(paths, **_):
            return b' '.join(path.read_bytes() for path in paths)

        with mock.patch.object(config, 'max_input_length', 100), \
                mock.patch.object(export, '_synthesize_cached', side_effect=speak), \
                mock.patch.object(export, 'concat_audio_files', side_effect=concatenate):
            result = await export.export_audio(ExportRequest(text=DOCUMENT))
        self.assertEqual(result.body.decode(), DOCUMENT)
        self.assertTrue(all(len(text) <= 100 for text in spoken))

    async def test_single_synthesis_keeps_input_limit(self):
        with self.assertRaises(HTTPException) as error:
            await synthesize.synthesize(SynthesizeRequest(text=DOCUMENT))
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn('Text exceeds max length', error.exception.detail)


if __name__ == '__main__':
    unittest.main()
