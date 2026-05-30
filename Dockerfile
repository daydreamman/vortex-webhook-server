# 使用官方 Python 輕量版作為 Base Image
FROM python:3.9-slim

# 設定環境變數，確保 Python 輸出直接寫入終端機（不緩衝）
ENV PYTHONUNBUFFERED=1

# 設定工作目錄
WORKDIR /app

# 複製 requirements.txt 並安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案程式碼
COPY . .

# 曝露 Port 8080 (Cloud Run / App Engine 預設)
EXPOSE 8080

# 使用 Gunicorn 作為 Production Web 伺服器啟動 Flask App
# Gunicorn 會將服務綁定到 0.0.0.0 和 Cloud Run 提供或預設的 8080 Port
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
