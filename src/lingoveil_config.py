from __future__ import annotations
from dataclasses import dataclass, replace
from pathlib import Path
TRANSLATION_ENGINE_BERGAMOT = "bergamot"
TRANSLATION_ENGINE_SEAMLESS_M4T = "seamless_m4t"
TRANSLATION_ENGINE_LM_STUDIO = "lm_studio"
SUPPORTED_TRANSLATION_ENGINES = {
    TRANSLATION_ENGINE_BERGAMOT,
    TRANSLATION_ENGINE_SEAMLESS_M4T,
    TRANSLATION_ENGINE_LM_STUDIO,
}

DEFAULT_TRANSLATION_ENGINE = TRANSLATION_ENGINE_BERGAMOT
DEFAULT_BROWSER_PORT = 8765
SEAMLESS_DEFAULT_MODEL_ID = "facebook/seamless-m4t-v2-large"
SEAMLESS_DEFAULT_MODEL_REVISION = "5f8cc790b19fc3f67a61c105133b20b34e3dcb76"
@dataclass(frozen=True)

class LlmSettings:
    base_url: str
    model: str
    timeout_sec: float
    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/chat/completions"
@dataclass(frozen=True)

class BergamotSettings:
    node_bin: str
    timeout_sec: float
    source_lang: str
    target_lang: str
@dataclass(frozen=True)

class BergamotPreprocessSettings:
    enabled: bool
    mode: str
    normalization_enabled: bool
    glossary_enabled: bool
    symspell_enabled: bool
    languagetool_enabled: bool
    languagetool_timeout_sec: float
    preprocess_version: str
    glossary_path: Path
    symspell_dict_path: Path
@dataclass(frozen=True)

class SeamlessM4TSettings:
    model_id: str
    model_revision: str
    model_dir: str
    source_lang: str
    target_lang: str
    device: str
    license_accepted: bool
@dataclass(frozen=True)

class BrowserSettings:
    port: int
    access_code: str
@dataclass(frozen=True)

class TranslationSettings:
    translation_engine: str
    llm: LlmSettings
    bergamot: BergamotSettings
    seamless: SeamlessM4TSettings
    preprocess: BergamotPreprocessSettings
    browser: BrowserSettings
def load_env_file(path: Path) -> dict[str, str]:
    pass
    values: dict[str, str] = {}

    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")

        key = key.strip()

        value = value.strip().strip('"').strip("'")

        if key:
            values[key] = value
    return values
def _parse_float(value: str, default: float) -> float:
    try:
        return float(value)

    except ValueError:
        return default
def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)

    except ValueError:
        return default
def validate_translation_engine(engine: str) -> str:
    normalized = engine.strip().lower()

    if normalized not in SUPPORTED_TRANSLATION_ENGINES:
        supported = ", ".join(sorted(SUPPORTED_TRANSLATION_ENGINES))

        raise ValueError(
            f"Ungültige Übersetzungsengine '{engine}'. "
            f"Erlaubt: {supported}"
        )

    return normalized
def load_llm_settings(env_path: Path) -> LlmSettings:
    env = load_env_file(env_path)

    base_url = env.get("LINGOVEIL_LLM_BASE_URL", "http://127.0.0.1:1234")

    model = env.get("LINGOVEIL_LLM_MODEL", "openai/gpt-oss-20b")

    timeout_sec = _parse_float(env.get("LINGOVEIL_LLM_TIMEOUT_SEC", "120"), 120.0)

    return LlmSettings(base_url=base_url, model=model, timeout_sec=timeout_sec)

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent
def _parse_bool(value: str, default: bool) -> bool:
    normalized = value.strip().lower()

    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default
def _normalize_browser_port(value: str, default: int = DEFAULT_BROWSER_PORT) -> int:
    port = _parse_int(value.strip(), default)

    if 1 <= port <= 65535:
        return port
    return default
def _normalize_browser_access_code(value: str) -> str:
    code = "".join(ch for ch in value.strip() if ch.isdigit())

    if not code:
        return ""
    if len(code) != 4:
        raise ValueError("Browser-Code muss aus genau 4 Ziffern bestehen")

    return code
def load_bergamot_preprocess_settings(env_path: Path) -> BergamotPreprocessSettings:
    env = load_env_file(env_path)

    root = _project_root()

    return BergamotPreprocessSettings(
        enabled=_parse_bool(env.get("LINGOVEIL_BERGAMOT_PREPROCESS_ENABLED", "true"), True),
        mode=env.get("LINGOVEIL_BERGAMOT_PREPROCESS_MODE", "standard"),
        normalization_enabled=_parse_bool(
            env.get("LINGOVEIL_BERGAMOT_NORMALIZATION_ENABLED", "true"), True
        ),
        glossary_enabled=_parse_bool(
            env.get("LINGOVEIL_BERGAMOT_GLOSSARY_ENABLED", "true"), True
        ),
        symspell_enabled=_parse_bool(
            env.get("LINGOVEIL_BERGAMOT_SYMSPELL_ENABLED", "true"), True
        ),
        languagetool_enabled=_parse_bool(
            env.get("LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED", "false"), False
        ),
        languagetool_timeout_sec=_parse_float(
            env.get("LINGOVEIL_BERGAMOT_LANGUAGETOOL_TIMEOUT_SEC", "5"), 5.0
        ),
        preprocess_version=env.get(
            "LINGOVEIL_BERGAMOT_PREPROCESS_VERSION", "preprocess-v1"
        ),
        glossary_path=root / "config" / "ocr_glossary.json",
        symspell_dict_path=root / "resources" / "symspell" / "frequency_dictionary_en_82_765.txt",
    )

def load_seamless_settings(env_path: Path) -> SeamlessM4TSettings:
    env = load_env_file(env_path)

    return SeamlessM4TSettings(
        model_id=env.get("LINGOVEIL_SEAMLESS_MODEL_ID", SEAMLESS_DEFAULT_MODEL_ID),
        model_revision=env.get(
            "LINGOVEIL_SEAMLESS_MODEL_REVISION", SEAMLESS_DEFAULT_MODEL_REVISION
        ),
        model_dir=env.get("LINGOVEIL_SEAMLESS_MODEL_DIR", "").strip(),
        source_lang=env.get("LINGOVEIL_SEAMLESS_SOURCE_LANG", "eng"),
        target_lang=env.get("LINGOVEIL_SEAMLESS_TARGET_LANG", "deu"),
        device=env.get("LINGOVEIL_SEAMLESS_DEVICE", "auto"),
        license_accepted=_parse_bool(
            env.get("LINGOVEIL_SEAMLESS_LICENSE_ACCEPTED", "false"), False
        ),
    )

def load_browser_settings(env_path: Path) -> BrowserSettings:
    env = load_env_file(env_path)

    port = _normalize_browser_port(
        env.get("LINGOVEIL_BROWSER_PORT", str(DEFAULT_BROWSER_PORT)),
        DEFAULT_BROWSER_PORT,
    )

    raw_code = env.get("LINGOVEIL_BROWSER_ACCESS_CODE", "").strip()

    try:
        access_code = _normalize_browser_access_code(raw_code)

    except ValueError:
        access_code = ""
    return BrowserSettings(port=port, access_code=access_code)

def load_translation_settings(env_path: Path) -> TranslationSettings:
    env = load_env_file(env_path)

    engine_raw = env.get("LINGOVEIL_TRANSLATION_ENGINE", DEFAULT_TRANSLATION_ENGINE)

    engine = validate_translation_engine(engine_raw)

    llm = load_llm_settings(env_path)

    bergamot = BergamotSettings(
        node_bin=env.get("LINGOVEIL_BERGAMOT_NODE_BIN", "node"),
        timeout_sec=_parse_float(
            env.get("LINGOVEIL_BERGAMOT_TIMEOUT_SEC", "30"), 30.0
        ),
        source_lang=env.get("LINGOVEIL_BERGAMOT_SOURCE_LANG", "en"),
        target_lang=env.get("LINGOVEIL_BERGAMOT_TARGET_LANG", "de"),
    )

    seamless = load_seamless_settings(env_path)

    preprocess = load_bergamot_preprocess_settings(env_path)

    return TranslationSettings(
        translation_engine=engine,
        llm=llm,
        bergamot=bergamot,
        seamless=seamless,
        preprocess=preprocess,
        browser=load_browser_settings(env_path),
    )

def save_llm_env(
    path: Path,
    *,
    base_url: str,
    model: str,
    timeout_sec: float,
) -> None:
    pass
    existing = load_env_file(path)

    existing["LINGOVEIL_LLM_BASE_URL"] = base_url.strip().rstrip("/")

    existing["LINGOVEIL_LLM_MODEL"] = model.strip()

    timeout_value = (
        str(int(timeout_sec))

        if timeout_sec == int(timeout_sec)

        else str(timeout_sec)

    )

    existing["LINGOVEIL_LLM_TIMEOUT_SEC"] = timeout_value
    _write_env_file(path, existing)

def save_preprocess_env(
    path: Path,
    *,
    preprocess: BergamotPreprocessSettings,
) -> None:
    existing = load_env_file(path)

    existing["LINGOVEIL_BERGAMOT_PREPROCESS_ENABLED"] = _bool_str(preprocess.enabled)

    existing["LINGOVEIL_BERGAMOT_PREPROCESS_MODE"] = preprocess.mode
    existing["LINGOVEIL_BERGAMOT_NORMALIZATION_ENABLED"] = _bool_str(
        preprocess.normalization_enabled
    )

    existing["LINGOVEIL_BERGAMOT_GLOSSARY_ENABLED"] = _bool_str(preprocess.glossary_enabled)

    existing["LINGOVEIL_BERGAMOT_SYMSPELL_ENABLED"] = _bool_str(preprocess.symspell_enabled)

    existing["LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED"] = _bool_str(
        preprocess.languagetool_enabled
    )

    existing["LINGOVEIL_BERGAMOT_LANGUAGETOOL_TIMEOUT_SEC"] = str(
        int(preprocess.languagetool_timeout_sec)

        if preprocess.languagetool_timeout_sec == int(preprocess.languagetool_timeout_sec)

        else preprocess.languagetool_timeout_sec
    )

    existing["LINGOVEIL_BERGAMOT_PREPROCESS_VERSION"] = preprocess.preprocess_version
    _write_env_file(path, existing)

def save_seamless_env(
    path: Path,
    *,
    seamless: SeamlessM4TSettings,
) -> None:
    existing = load_env_file(path)

    existing["LINGOVEIL_SEAMLESS_MODEL_ID"] = seamless.model_id.strip()

    existing["LINGOVEIL_SEAMLESS_MODEL_REVISION"] = seamless.model_revision.strip()

    existing["LINGOVEIL_SEAMLESS_MODEL_DIR"] = seamless.model_dir.strip()

    existing["LINGOVEIL_SEAMLESS_SOURCE_LANG"] = seamless.source_lang.strip() or "eng"
    existing["LINGOVEIL_SEAMLESS_TARGET_LANG"] = seamless.target_lang.strip() or "deu"
    existing["LINGOVEIL_SEAMLESS_DEVICE"] = seamless.device.strip() or "auto"
    existing["LINGOVEIL_SEAMLESS_LICENSE_ACCEPTED"] = _bool_str(seamless.license_accepted)

    _write_env_file(path, existing)

def save_browser_env(
    path: Path,
    *,
    browser: BrowserSettings,
) -> None:
    existing = load_env_file(path)

    existing["LINGOVEIL_BROWSER_PORT"] = str(_normalize_browser_port(str(browser.port)))

    existing["LINGOVEIL_BROWSER_ACCESS_CODE"] = _normalize_browser_access_code(
        browser.access_code
    )

    _write_env_file(path, existing)

def save_translation_env(
    path: Path,
    *,
    translation_engine: str,
    bergamot_node_bin: str,
    bergamot_timeout_sec: float,
    bergamot_source_lang: str,
    bergamot_target_lang: str,
    llm_base_url: str,
    llm_model: str,
    llm_timeout_sec: float,
    preprocess: BergamotPreprocessSettings | None = None,
    seamless: SeamlessM4TSettings | None = None,
    browser: BrowserSettings | None = None,
) -> None:
    pass
    engine = validate_translation_engine(translation_engine)

    existing = load_env_file(path)

    existing["LINGOVEIL_TRANSLATION_ENGINE"] = engine
    existing["LINGOVEIL_BERGAMOT_NODE_BIN"] = bergamot_node_bin.strip() or "node"
    existing["LINGOVEIL_BERGAMOT_TIMEOUT_SEC"] = str(
        int(bergamot_timeout_sec)

        if bergamot_timeout_sec == int(bergamot_timeout_sec)

        else bergamot_timeout_sec
    )

    existing["LINGOVEIL_BERGAMOT_SOURCE_LANG"] = bergamot_source_lang.strip() or "en"
    existing["LINGOVEIL_BERGAMOT_TARGET_LANG"] = bergamot_target_lang.strip() or "de"
    existing["LINGOVEIL_LLM_BASE_URL"] = llm_base_url.strip().rstrip("/")

    existing["LINGOVEIL_LLM_MODEL"] = llm_model.strip()

    existing["LINGOVEIL_LLM_TIMEOUT_SEC"] = str(
        int(llm_timeout_sec)

        if llm_timeout_sec == int(llm_timeout_sec)

        else llm_timeout_sec
    )

    if preprocess is not None:
        existing["LINGOVEIL_BERGAMOT_PREPROCESS_ENABLED"] = _bool_str(preprocess.enabled)

        existing["LINGOVEIL_BERGAMOT_PREPROCESS_MODE"] = preprocess.mode
        existing["LINGOVEIL_BERGAMOT_NORMALIZATION_ENABLED"] = _bool_str(
            preprocess.normalization_enabled
        )

        existing["LINGOVEIL_BERGAMOT_GLOSSARY_ENABLED"] = _bool_str(
            preprocess.glossary_enabled
        )

        existing["LINGOVEIL_BERGAMOT_SYMSPELL_ENABLED"] = _bool_str(
            preprocess.symspell_enabled
        )

        existing["LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED"] = _bool_str(
            preprocess.languagetool_enabled
        )

        existing["LINGOVEIL_BERGAMOT_LANGUAGETOOL_TIMEOUT_SEC"] = str(
            int(preprocess.languagetool_timeout_sec)

            if preprocess.languagetool_timeout_sec
            == int(preprocess.languagetool_timeout_sec)

            else preprocess.languagetool_timeout_sec
        )

        existing["LINGOVEIL_BERGAMOT_PREPROCESS_VERSION"] = preprocess.preprocess_version
    if seamless is not None:
        existing["LINGOVEIL_SEAMLESS_MODEL_ID"] = seamless.model_id.strip()

        existing["LINGOVEIL_SEAMLESS_MODEL_REVISION"] = seamless.model_revision.strip()

        existing["LINGOVEIL_SEAMLESS_MODEL_DIR"] = seamless.model_dir.strip()

        existing["LINGOVEIL_SEAMLESS_SOURCE_LANG"] = seamless.source_lang.strip() or "eng"
        existing["LINGOVEIL_SEAMLESS_TARGET_LANG"] = seamless.target_lang.strip() or "deu"
        existing["LINGOVEIL_SEAMLESS_DEVICE"] = seamless.device.strip() or "auto"
        existing["LINGOVEIL_SEAMLESS_LICENSE_ACCEPTED"] = _bool_str(
            seamless.license_accepted
        )

    if browser is not None:
        existing["LINGOVEIL_BROWSER_PORT"] = str(
            _normalize_browser_port(str(browser.port))

        )

        existing["LINGOVEIL_BROWSER_ACCESS_CODE"] = _normalize_browser_access_code(
            browser.access_code
        )

    _write_env_file(path, existing)

def _bool_str(value: bool) -> str:
    return "true" if value else "false"
def _write_env_file(path: Path, values: dict[str, str]) -> None:
    order = [
        "LINGOVEIL_TRANSLATION_ENGINE",
        "LINGOVEIL_BERGAMOT_NODE_BIN",
        "LINGOVEIL_BERGAMOT_TIMEOUT_SEC",
        "LINGOVEIL_BERGAMOT_SOURCE_LANG",
        "LINGOVEIL_BERGAMOT_TARGET_LANG",
        "LINGOVEIL_BERGAMOT_PREPROCESS_ENABLED",
        "LINGOVEIL_BERGAMOT_PREPROCESS_MODE",
        "LINGOVEIL_BERGAMOT_NORMALIZATION_ENABLED",
        "LINGOVEIL_BERGAMOT_GLOSSARY_ENABLED",
        "LINGOVEIL_BERGAMOT_SYMSPELL_ENABLED",
        "LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED",
        "LINGOVEIL_BERGAMOT_LANGUAGETOOL_TIMEOUT_SEC",
        "LINGOVEIL_BERGAMOT_PREPROCESS_VERSION",
        "LINGOVEIL_LLM_BASE_URL",
        "LINGOVEIL_LLM_MODEL",
        "LINGOVEIL_LLM_TIMEOUT_SEC",
        "LINGOVEIL_SEAMLESS_MODEL_ID",
        "LINGOVEIL_SEAMLESS_MODEL_REVISION",
        "LINGOVEIL_SEAMLESS_MODEL_DIR",
        "LINGOVEIL_SEAMLESS_SOURCE_LANG",
        "LINGOVEIL_SEAMLESS_TARGET_LANG",
        "LINGOVEIL_SEAMLESS_DEVICE",
        "LINGOVEIL_SEAMLESS_LICENSE_ACCEPTED",
        "LINGOVEIL_BROWSER_PORT",
        "LINGOVEIL_BROWSER_ACCESS_CODE",
    ]
    lines: list[str] = []
    for key in order:
        if key in values:
            lines.append(f"{key}={values[key]}")

    for key, value in values.items():
        if key not in order:
            lines.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
