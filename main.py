from modules.config import logger, SETTINGS, MP_API_KEY

def main():
    logger.info("--- 项目初始化启动 ---")
    
    # 打印部分配置确认
    tolerance = SETTINGS.get('matching', {}).get('default_tolerance')
    logger.info(f"当前系统匹配容差设定为: {tolerance}")
    
    if MP_API_KEY:
        logger.info("核心服务状态: 正常")
    else:
        logger.error("核心服务状态: API缺失")

if __name__ == "__main__":
    main()