# AgentBook · 零依赖 Docker 镜像（仅用 Python 标准库）
# 用法见仓库 README「Docker 一键分发」。
FROM python:3-slim

# 实时日志（首次登录密码会打印到 stdout，便于 docker logs 查看）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 运行时数据（密码 / API Key / 配置）统一落到 /data，由 compose 挂载命名卷持久化。
# 这样镜像本身不含任何敏感信息：config.json / 密钥都随卷走，重建容器不丢。
ENV AN_WEB_DIR=/data

WORKDIR /app

# 复制应用源码（零 pip 依赖，无需 requirements.txt / 无需 pip install）。
# 敏感文件与构建产物由仓库根 .dockerignore 排除，不会进镜像。
COPY . /app/

# 运行时数据目录（compose 把命名卷挂到这里）
RUN mkdir -p /data

EXPOSE 8080

# 入口：host / port / 密码均可经环境变量覆盖
#   AN_WEB_HOST       默认 0.0.0.0
#   AN_WEB_PORT       默认 8080
#   AN_AGENT_PASSWORD 设置则用作登录密码；不设置则首次启动随机生成并写入 /data
CMD ["python3", "server.py"]
