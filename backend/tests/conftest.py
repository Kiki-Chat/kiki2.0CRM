def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: hits the real ElevenLabs test agent (skip in CI with -m 'not live')",
    )
