import os
import json

# ==================== Configuration ====================
# Cookie credentials are stored in config.json. Keep this source template empty.
DEFAULT_COOKIES = {
    'ipb_member_id': '',
    'ipb_pass_hash': '',
    'igneous': '',
    'nw': '1',
    "star": ""
}

# ==================== Config and cookies ====================
def get_config_path():
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(current_dir, "config.json")

def create_default_config():
    config_path = get_config_path()
    
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_COOKIES, f, ensure_ascii=False, indent=2)
            print(f"Created empty config template: {config_path}")
        except Exception as e:
            print(f"Failed to create config file: {e}")
    
    return config_path

def load_config_from_file():
    config_path = get_config_path()
    
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config
        else:
            print(f"Config file does not exist: {config_path}")
            return None
    except Exception as e:
        print(f"Failed to read config file: {e}")
        return None

def has_usable_cookies(cookies: dict) -> bool:
    required_cookie_names = ("ipb_member_id", "ipb_pass_hash")
    return all(str(cookies.get(name, "")).strip() for name in required_cookie_names)

def load_runtime_cookies():
    config_path = create_default_config()
    config = load_config_from_file()
    if config and has_usable_cookies(config):
        print(f"Loaded cookie config: {config_path}")
        return config

    print(f"Cookie config is missing or empty: {config_path}")
    choice = input("Continue with empty cookies? (y/N): ").strip().lower()
    if choice in ["y", "yes"]:
        print("Using empty cookies. Requests may fail.")
        return DEFAULT_COOKIES.copy()

    print("Program exited. Fill config.json and run again.")
    return None