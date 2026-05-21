import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import openai_config, llm_config_list

def test_openai_config_has_required_keys():
    cfg = openai_config("gpt-4o-mini", "sk-test-key")
    assert cfg["model"] == "gpt-4o-mini"
    assert cfg["api_key"] == "sk-test-key"
    assert cfg["api_type"] == "openai"

def test_openai_config_no_azure_keys():
    cfg = openai_config("gpt-4o-mini", "sk-test-key")
    assert "base_url" not in cfg
    assert "api_version" not in cfg

def test_llm_config_list_has_cache_seed():
    cfg = llm_config_list(seed=42, config_list=[{"model": "gpt-4o-mini", "api_key": "sk-x"}])
    assert cfg["cache_seed"] == 42
    assert cfg["temperature"] == 0
    assert cfg["timeout"] == 120
    assert len(cfg["functions"]) == 1
    assert cfg["functions"][0]["name"] == "python"
