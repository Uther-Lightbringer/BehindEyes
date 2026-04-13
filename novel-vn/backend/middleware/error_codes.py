"""
错误代码定义
"""

class ErrorCode:
    """错误代码枚举"""

    # 通用错误 (1xxx)
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # 认证错误 (2xxx)
    UNAUTHORIZED = "UNAUTHORIZED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"

    # 权限错误 (3xxx)
    FORBIDDEN = "FORBIDDEN"
    NOT_OWNER = "NOT_OWNER"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"

    # 资源错误 (4xxx)
    NOT_FOUND = "NOT_FOUND"
    NOVEL_NOT_FOUND = "NOVEL_NOT_FOUND"
    CHAPTER_NOT_FOUND = "CHAPTER_NOT_FOUND"
    CHARACTER_NOT_FOUND = "CHARACTER_NOT_FOUND"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    SAVE_NOT_FOUND = "SAVE_NOT_FOUND"

    # 业务错误 (5xxx)
    PARSE_FAILED = "PARSE_FAILED"
    GENERATION_FAILED = "GENERATION_FAILED"
    LLM_ERROR = "LLM_ERROR"
    IMAGE_ERROR = "IMAGE_ERROR"
    TREE_NOT_FOUND = "TREE_NOT_FOUND"

    # 参数错误 (6xxx)
    INVALID_PARAMETER = "INVALID_PARAMETER"
    INVALID_CHAPTER_INDEX = "INVALID_CHAPTER_INDEX"
    INVALID_CHARACTER_ID = "INVALID_CHARACTER_ID"
    INVALID_VISIBILITY = "INVALID_VISIBILITY"
    INVALID_ART_STYLE = "INVALID_ART_STYLE"


# 错误消息映射
ERROR_MESSAGES = {
    ErrorCode.UNKNOWN_ERROR: "未知错误",
    ErrorCode.INVALID_REQUEST: "无效的请求",
    ErrorCode.VALIDATION_ERROR: "参数验证失败",

    ErrorCode.UNAUTHORIZED: "未授权",
    ErrorCode.TOKEN_EXPIRED: "登录已过期",
    ErrorCode.INVALID_TOKEN: "无效的登录凭证",
    ErrorCode.LOGIN_REQUIRED: "请先登录",

    ErrorCode.FORBIDDEN: "无权访问",
    ErrorCode.NOT_OWNER: "您不是资源所有者",
    ErrorCode.ADMIN_REQUIRED: "需要管理员权限",

    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.NOVEL_NOT_FOUND: "小说不存在",
    ErrorCode.CHAPTER_NOT_FOUND: "章节不存在",
    ErrorCode.CHARACTER_NOT_FOUND: "角色不存在",
    ErrorCode.TASK_NOT_FOUND: "任务不存在",
    ErrorCode.SAVE_NOT_FOUND: "存档不存在",

    ErrorCode.PARSE_FAILED: "解析失败",
    ErrorCode.GENERATION_FAILED: "生成失败",
    ErrorCode.LLM_ERROR: "AI服务错误",
    ErrorCode.IMAGE_ERROR: "图片生成错误",
    ErrorCode.TREE_NOT_FOUND: "树结构不存在或已过期",

    ErrorCode.INVALID_PARAMETER: "参数无效",
    ErrorCode.INVALID_CHAPTER_INDEX: "章节索引无效",
    ErrorCode.INVALID_CHARACTER_ID: "角色ID无效",
    ErrorCode.INVALID_VISIBILITY: "可见性参数无效",
    ErrorCode.INVALID_ART_STYLE: "不支持的艺术风格",
}
