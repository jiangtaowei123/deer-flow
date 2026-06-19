# Kickart Clone Dockerfile - 生产级容器化
# 多阶段构建：构建阶段 + 运行阶段

# ============ 构建阶段 ============
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt ./

# 安装 Python 依赖到 /install
RUN pip install --user --no-cache-dir -r requirements.txt

# ============ 运行阶段 ============
FROM python:3.11-slim AS runtime

LABEL maintainer="kickart-clone"
LABEL version="1.0.0"
LABEL description="一站式营销创作平台 - 商品解析 + 创意生成 + 视频成片"

WORKDIR /app

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu \
    fonts-noto-cjk \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

# 从构建阶段复制 Python 包
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app

# 复制应用代码
COPY . /app/

# 创建数据目录
RUN mkdir -p /data/runs /data/videos /data/audio /data/images \
    /data/jnpf /data/compound_registry /data/tenants /data/monitoring /data/logs

# 环境变量默认值
ENV KICKART_ENVIRONMENT=production \
    KICKART_API_HOST=0.0.0.0 \
    KICKART_API_PORT=8765 \
    KICKART_LOG_LEVEL=INFO \
    KICKART_LOG_FORMAT=json \
    KICKART_LOG_FILE=/data/logs/app.log \
    KICKART_LEAD_AGENT_OUTPUT_DIR=/data/runs \
    KICKART_VIDEO_OUTPUT_DIR=/data/videos \
    KICKART_TTS_OUTPUT_DIR=/data/audio \
    KICKART_JNPF_OUTPUT_DIR=/data/jnpf \
    KICKART_COMPOUND_REGISTRY_DIR=/data/compound_registry \
    KICKART_TENANT_STORAGE_DIR=/data/tenants \
    KICKART_MONITORING_STORAGE_DIR=/data/monitoring \
    KICKART_SD_WEBUI_URL=http://host.docker.internal:7860

# 暴露端口
EXPOSE 8765

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

# 数据卷
VOLUME ["/data"]

# 启动命令
CMD ["python", "-m", "uvicorn", "backend.api.api:app", \
     "--host", "0.0.0.0", \
     "--port", "8765", \
     "--workers", "4", \
     "--log-level", "info"]
