CONFIG_PATH = "esp32_config.txt"

CONFIG_DEFAULTS = {
    "rts_state": "1",
}

def load_config():
    settings = dict(CONFIG_DEFAULTS)
    try:
        with open(CONFIG_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    if key in settings:
                        settings[key] = value.strip()
    except OSError:
        save_config(settings)
    return settings

def save_config(settings):
    with open(CONFIG_PATH, "w") as f:
        for key in CONFIG_DEFAULTS:
            f.write(f"{key}={settings.get(key, '')}\n")