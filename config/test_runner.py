"""Test runner that forces external providers to their offline mocks.

The real provider switches live in ``.env``, which the test process also loads.
Without this override, running the suite after enabling DeepSeek or Volcengine
would make paid network calls and could bill the account.
"""

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class OfflineProvidersTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        self._offline_override = override_settings(
            TRANSLATION_PROVIDER="mock",
            TTS_PROVIDER="mock",
            DEEPSEEK_API_KEY="",
            VOLCENGINE_APP_ID="",
            VOLCENGINE_ACCESS_TOKEN="",
            VOLCENGINE_TTS_VOICE="",
        )
        self._offline_override.enable()
        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        self._offline_override.disable()
