import pytest
from pathlib import Path

from aaosa.config.role_providers import RoleProvider, RoleProviders, load_role_providers


def _write(tmp_path: Path, content: str, name: str = "roles.yaml") -> Path:
    """Helper to write content to a YAML file in tmp_path."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestRoleProvider:
    def test_role_provider_defaults(self):
        """RoleProvider with no args has None provider and None model."""
        rp = RoleProvider()
        assert rp.provider is None
        assert rp.model is None

    def test_role_provider_provider_only(self):
        """RoleProvider can set provider without model."""
        rp = RoleProvider(provider="openai")
        assert rp.provider == "openai"
        assert rp.model is None

    def test_role_provider_model_only(self):
        """RoleProvider can set model without provider."""
        rp = RoleProvider(model="gpt-4o")
        assert rp.provider is None
        assert rp.model == "gpt-4o"

    def test_role_provider_both(self):
        """RoleProvider can set both provider and model."""
        rp = RoleProvider(provider="ollama", model="llama3.1")
        assert rp.provider == "ollama"
        assert rp.model == "llama3.1"

    def test_role_provider_extra_forbid(self):
        """RoleProvider rejects unknown fields."""
        with pytest.raises(ValueError, match="extra_field"):
            RoleProvider(provider="openai", extra_field="should_fail")


class TestRoleProviders:
    def test_role_providers_all_defaults(self):
        """RoleProviders with no args has all roles as empty RoleProvider()."""
        rp = RoleProviders()
        assert rp.divider.provider is None and rp.divider.model is None
        assert rp.aggregator.provider is None and rp.aggregator.model is None
        assert rp.tagger.provider is None and rp.tagger.model is None
        assert rp.evaluator.provider is None and rp.evaluator.model is None
        assert rp.diagnostic.provider is None and rp.diagnostic.model is None
        assert rp.triage.provider is None and rp.triage.model is None
        assert rp.task_spec.provider is None and rp.task_spec.model is None

    def test_role_providers_partial_override(self):
        """RoleProviders can override specific roles, leaving others default."""
        rp = RoleProviders(
            divider=RoleProvider(provider="openai", model="gpt-4o"),
            evaluator=RoleProvider(model="gpt-4o-mini"),
        )
        # Override roles
        assert rp.divider.provider == "openai"
        assert rp.divider.model == "gpt-4o"
        assert rp.evaluator.provider is None
        assert rp.evaluator.model == "gpt-4o-mini"
        # Untouched roles
        assert rp.aggregator.provider is None
        assert rp.tagger.provider is None

    def test_role_providers_extra_forbid(self):
        """RoleProviders rejects unknown role keys."""
        with pytest.raises(ValueError, match="extra_role"):
            RoleProviders(extra_role=RoleProvider())


class TestLoadRoleProviders:
    def test_load_role_providers_path_none(self):
        """load_role_providers(None) returns an empty RoleProviders()."""
        rp = load_role_providers(None)
        assert isinstance(rp, RoleProviders)
        assert rp.divider.provider is None
        assert rp.aggregator.provider is None

    def test_load_role_providers_missing_file_explicit_path(self, tmp_path):
        """An explicit path to a non-existent file raises ValueError."""
        with pytest.raises(ValueError, match="Cannot read"):
            load_role_providers(tmp_path / "does_not_exist.yaml")

    def test_load_role_providers_valid_partial(self, tmp_path):
        """A valid YAML with partial roles populates matching roles."""
        yaml_content = """\
divider:
  provider: openai
  model: gpt-4o
evaluator:
  model: gpt-4o-mini
"""
        path = _write(tmp_path, yaml_content)
        rp = load_role_providers(path)

        # Override roles
        assert rp.divider.provider == "openai"
        assert rp.divider.model == "gpt-4o"
        assert rp.evaluator.provider is None
        assert rp.evaluator.model == "gpt-4o-mini"
        # Untouched roles
        assert rp.aggregator.provider is None
        assert rp.tagger.provider is None

    def test_load_role_providers_malformed_yaml(self, tmp_path):
        """Syntactically invalid YAML raises ValueError."""
        bad = "divider:\n  provider: openai\n  model: gpt-4o\n  broken:\n    "  # trailing colon without proper block
        path = _write(tmp_path, bad)
        # This may parse as a nested dict with broken field, which is invalid
        # Accept either Malformed YAML or Invalid role providers
        with pytest.raises(ValueError):
            load_role_providers(path)

    def test_load_role_providers_not_a_mapping(self, tmp_path):
        """YAML that is a list or scalar instead of mapping raises ValueError."""
        path = _write(tmp_path, "- divider\n- aggregator")
        with pytest.raises(ValueError, match="Expected.*mapping"):
            load_role_providers(path)

    def test_load_role_providers_scalar_yaml(self, tmp_path):
        """YAML that is a scalar raises ValueError."""
        path = _write(tmp_path, "just_a_string")
        with pytest.raises(ValueError, match="Expected.*mapping"):
            load_role_providers(path)

    def test_load_role_providers_empty_yaml(self, tmp_path):
        """An empty YAML file (parses as None) returns RoleProviders()."""
        path = _write(tmp_path, "")
        rp = load_role_providers(path)
        assert isinstance(rp, RoleProviders)
        assert rp.divider.provider is None

    def test_load_role_providers_empty_mapping(self, tmp_path):
        """An empty mapping {} returns RoleProviders()."""
        path = _write(tmp_path, "{}")
        rp = load_role_providers(path)
        assert isinstance(rp, RoleProviders)
        assert rp.divider.provider is None

    def test_load_role_providers_unknown_role_key(self, tmp_path):
        """An unknown role key raises ValueError mentioning the key."""
        yaml_content = """\
divider:
  provider: openai
unknown_role:
  provider: ollama
"""
        path = _write(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="unknown_role"):
            load_role_providers(path)

    def test_load_role_providers_invalid_provider_value(self, tmp_path):
        """Invalid structure for a role value raises ValueError."""
        yaml_content = """\
divider:
  provider: openai
  model: gpt-4o
aggregator: just_a_string
"""
        path = _write(tmp_path, yaml_content)
        with pytest.raises(ValueError):
            load_role_providers(path)

    def test_load_role_providers_all_roles(self, tmp_path):
        """Loading all seven roles in one YAML works."""
        yaml_content = """\
divider:
  provider: openai
  model: gpt-4o
aggregator:
  provider: openai
tagger:
  model: gpt-4o-mini
evaluator:
  provider: ollama
  model: llama3.1
diagnostic:
  provider: ollama
triage:
  model: custom-model
task_spec:
  provider: openai
"""
        path = _write(tmp_path, yaml_content)
        rp = load_role_providers(path)

        assert rp.divider.provider == "openai"
        assert rp.divider.model == "gpt-4o"
        assert rp.aggregator.provider == "openai"
        assert rp.aggregator.model is None
        assert rp.tagger.provider is None
        assert rp.tagger.model == "gpt-4o-mini"
        assert rp.evaluator.provider == "ollama"
        assert rp.evaluator.model == "llama3.1"
        assert rp.diagnostic.provider == "ollama"
        assert rp.diagnostic.model is None
        assert rp.triage.provider is None
        assert rp.triage.model == "custom-model"
        assert rp.task_spec.provider == "openai"
        assert rp.task_spec.model is None

    def test_load_role_providers_returns_type(self, tmp_path):
        """load_role_providers always returns RoleProviders type."""
        path = _write(tmp_path, "{}")
        rp = load_role_providers(path)
        assert isinstance(rp, RoleProviders)

        rp_none = load_role_providers(None)
        assert isinstance(rp_none, RoleProviders)
