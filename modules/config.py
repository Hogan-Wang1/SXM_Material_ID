import os
import logging
from logging.handlers import RotatingFileHandler
import yaml
from pathlib import Path
from dotenv import load_dotenv

# 1. 自动定位项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. 加载 .env 环境变量
load_dotenv(BASE_DIR / ".env")
MP_API_KEY = os.getenv("MP_API_KEY")

# 3. 定义内置默认配置 (防线：确保即使 YAML 丢失，程序也不会因为缺少键值对而崩溃)
DEFAULT_SETTINGS = {
    'preprocessing': {
        'sigma': 1.0,
        'auto_flatten': True
    },
    'matching': {
        'default_tolerance': 0.05,
        'angle_tolerance': 2.0,
        'min_confidence': 0.7
    },
    'database': {
        'provider': "Materials Project",
        'cache_results': True
    }
}

# 4. 配置日志系统 (引入 RotatingFileHandler 防止日志无限膨胀)
def setup_logging():
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    
    log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    
    # 建立滚动日志：单个文件最大 5MB，保留最近 3 个备份
    file_handler = RotatingFileHandler(
        log_dir / "app.log", 
        maxBytes=5*1024*1024, 
        backupCount=3, 
        encoding='utf-8'
    )
    stream_handler = logging.StreamHandler()
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[file_handler, stream_handler]
    )
    return logging.getLogger("SXM_Project")

logger = setup_logging()

# 5. 动态加载 YAML 配置 (支持指定不同路径，具备默认值注入功能)
def load_settings(config_filename="settings.yaml"):
    yaml_path = BASE_DIR / "configs" / config_filename
    
    if not yaml_path.exists():
        logger.warning(f"未找到配置文件 {config_filename}，将使用内置默认物理参数。")
        return DEFAULT_SETTINGS

    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            user_settings = yaml.safe_load(f) or {}
            
            # 深度合并：确保即使 YAML 里少写了几行，程序也能从默认值里找补
            final_settings = DEFAULT_SETTINGS.copy()
            for key, value in user_settings.items():
                if isinstance(value, dict) and key in final_settings:
                    final_settings[key].update(value)
                else:
                    final_settings[key] = value
                    
            logger.info(f"成功加载配置: {config_filename}")
            return final_settings
    except Exception as e:
        logger.error(f"读取配置文件出错，回退至默认设置: {e}")
        return DEFAULT_SETTINGS

# 导出全局设置
SETTINGS = load_settings()

# 6. API Key 脱敏验证
if not MP_API_KEY:
    logger.warning("环境变量中缺少 MP_API_KEY，数据库自动比对模块将无法启动。")
else:
    # 仅打印前5位，防止日志泄露完整 Key
    logger.info("API Key 加载成功 (Masked: %s...)", MP_API_KEY[:5])