# 軽量なPython 3.10環境を使用
FROM python:3.10-slim

# 作業ディレクトリの設定
WORKDIR /app

# 画像生成(Kaleido)に必要なシステムライブラリをインストール
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# ライブラリのインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# コードをコピー
COPY publication_tracker.py .

# コンテナ起動時に実行するコマンド
CMD ["python", "publication_tracker.py"]
