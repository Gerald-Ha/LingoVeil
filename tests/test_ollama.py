import json
import unittest
import httpx

from lingoveil_ollama import (
    OLLAMA_PROMPT_VERSION,
    OllamaSettings,
    OllamaTranslationError,
    OllamaTranslator,
    normalize_ollama_model_name,
    ollama_model_capabilities,
    ollama_supported_lingoveil_languages,
)

class OllamaTranslatorTests(unittest.TestCase):
    def make_client(self, handler, unavailable=None):
        return OllamaTranslator(
            OllamaSettings("http://ollama.test:11434", "translategemma:4b", 5, "5m"),
            transport=httpx.MockTransport(handler),
            unavailable_fn=unavailable,
        )

    def test_tags_show_chat_and_connection_test(self):
        paths = []
        def handler(request):
            paths.append(request.url.path)

            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{
                    "name": "translategemma:4b", "model": "translategemma:4b"
                }]})

            if request.url.path == "/api/show":
                return httpx.Response(200, json={"details": {"family": "gemma3"}})

            body = json.loads(request.content)

            self.assertFalse(body["stream"])

            self.assertEqual(body["keep_alive"], "5m")

            self.assertEqual(body["options"]["temperature"], 0)

            self.assertFalse(body["format"]["properties"]["translations"]["additionalProperties"])

            return httpx.Response(200, json={
                "message": {"content": '{"translations":{"TEST":"Hallo!"}}'},
                "load_duration": 10, "prompt_eval_duration": 20, "eval_duration": 30,
            })

        client = self.make_client(handler)

        try:
            result = client.test_connection()

        finally:
            client.close()

        self.assertTrue(result["available"])

        self.assertEqual(result["translation"], "Hallo!")

        self.assertEqual(paths, ["/api/tags", "/api/show", "/api/chat"])

    def test_optional_bridge_token_is_sent_and_direct_mode_has_no_authorization(self):
        headers = []
        def handler(request):
            headers.append(request.headers.get("authorization"))

            return httpx.Response(200, json={"models": []})

        direct = self.make_client(handler)

        direct.list_models()

        direct.close()

        bridged = OllamaTranslator(
            OllamaSettings(
                "http://bridge.test:11435", "translategemma:4b", 5, "5m", "secret"
            ),
            transport=httpx.MockTransport(handler),
        )

        bridged.list_models()

        bridged.close()

        self.assertEqual(headers, [None, "Bearer secret"])

    def test_bridge_status_diagnostics_do_not_expose_token(self):
        expected = {
            401: "Bridge-Authentifizierung fehlgeschlagen",
            403: "von der Bridge abgelehnt",
            502: "Ollama nicht verfügbar",
        }

        for status, message in expected.items():
            with self.subTest(status=status):
                client = OllamaTranslator(
                    OllamaSettings(
                        "http://bridge.test:11435", "translategemma:4b", 5, "5m", "secret"
                    ),
                    transport=httpx.MockTransport(
                        lambda request, code=status: httpx.Response(code, text="failure")

                    ),
                )

                with self.assertRaisesRegex(OllamaTranslationError, message) as raised:
                    client.list_models()

                client.close()

                self.assertNotIn("secret", str(raised.exception))

    def test_multiple_blocks_and_exact_ids(self):
        def handler(request):
            return httpx.Response(200, json={"message": {"content": json.dumps({
                "translations": {"G01": "Hallo", "G05": "Warte"}
            })}})

        client = self.make_client(handler)

        try:
            response = client.translate_blocks(
                [{"id": "G01", "text": "Hello"}, {"id": "G05", "text": "Wait"}],
                source_lang="eng", target_lang="deu",
            )

        finally:
            client.close()

        self.assertEqual([(i.block_id, i.translation) for i in response.items], [
            ("G01", "Hallo"), ("G05", "Warte")

        ])

    def test_invalid_json_retries_each_block_once(self):
        calls = 0
        def handler(request):
            nonlocal calls
            calls += 1
            body = json.loads(request.content)

            ids = body["format"]["properties"]["translations"]["required"]
            if calls == 1:
                return httpx.Response(200, json={"message": {"content": "not-json"}})

            block_id = ids[0]
            return httpx.Response(200, json={"message": {"content": json.dumps({
                "translations": {block_id: f"translated-{block_id}"}
            })}})

        client = self.make_client(handler)

        try:
            response = client.translate_blocks(
                [{"id": "G01", "text": "One"}, {"id": "G02", "text": "Two"}],
                source_lang="eng", target_lang="deu",
            )

        finally:
            client.close()

        self.assertEqual(calls, 3)

        self.assertEqual({item.block_id for item in response.items}, {"G01", "G02"})

    def test_missing_empty_changed_and_extra_ids_retry(self):
        scenarios = [
            {"G01": "Hallo"},
            {"G01": "Hallo", "G02": ""},
            {"G01": "Hallo", "G2": "Zwei"},
            {"G01": "Hallo", "G02": "Zwei", "EXTRA": "Nein"},
        ]
        for first in scenarios:
            with self.subTest(first=first):
                calls = 0
                def handler(request):
                    nonlocal calls
                    calls += 1
                    ids = json.loads(request.content)["format"]["properties"]["translations"]["required"]
                    translations = first if calls == 1 else {ids[0]: f"ok-{ids[0]}"}

                    return httpx.Response(200, json={"message": {"content": json.dumps({
                        "translations": translations
                    })}})

                client = self.make_client(handler)

                try:
                    result = client.translate_blocks(
                        [{"id": "G01", "text": "One"}, {"id": "G02", "text": "Two"}],
                        source_lang="eng", target_lang="deu",
                    )

                finally:
                    client.close()

                self.assertEqual({item.block_id for item in result.items}, {"G01", "G02"})

    def test_retry_failure_is_not_returned(self):
        def handler(request):
            return httpx.Response(200, json={"message": {"content": '{"translations":{}}'}})

        client = self.make_client(handler)

        with self.assertRaises(OllamaTranslationError):
            client.translate_blocks(
                [{"id": "G01", "text": "One"}], source_lang="eng", target_lang="deu"
            )

        client.close()

    def test_connection_refused_and_timeout_mark_unavailable(self):
        for error in (httpx.ConnectError("refused"), httpx.ReadTimeout("slow")):
            reasons = []
            def handler(request, current=error):
                raise current
            client = self.make_client(handler, reasons.append)

            with self.assertRaises(OllamaTranslationError):
                client.list_models()

            client.close()

            self.assertEqual(len(reasons), 1)

    def test_connect_timeout_has_short_specific_diagnostic(self):
        reasons = []
        client = self.make_client(
            lambda request: (_ for _ in ()).throw(httpx.ConnectTimeout("slow connect")),
            reasons.append,
        )

        with self.assertRaisesRegex(OllamaTranslationError, "Verbindungsaufbau.*5s"):
            client.list_models()

        client.close()

        self.assertEqual(reasons, ["Ollama-Verbindungsaufbau nach 5s abgebrochen"])

    def test_model_not_found(self):
        def handler(request):
            return httpx.Response(200, json={"models": []})

        client = self.make_client(handler)

        with self.assertRaisesRegex(OllamaTranslationError, "nicht installiert"):
            client.test_connection()

        client.close()

    def test_capability_registry_is_name_based(self):
        self.assertEqual(normalize_ollama_model_name(" TranslateGemma:4B "), "translategemma:4b")

        self.assertTrue(ollama_model_capabilities("translategemma:4b")["tested"])

        self.assertFalse(ollama_model_capabilities("gemma3:4b")["capabilities_known"])

        self.assertIn("deu", ollama_supported_lingoveil_languages("translategemma:4b"))

        self.assertEqual(OLLAMA_PROMPT_VERSION, "ollama-translategemma-v1")

if __name__ == "__main__":
    unittest.main()
