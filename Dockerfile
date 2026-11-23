FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . \
    && useradd --create-home app && mkdir /app/output && chown app:app /app/output
USER app
ENV MCP_TRANSPORT=http HOST=0.0.0.0 PORT=8000 OUTPUT_DIR=/app/output
EXPOSE 8000
CMD ["meeting-notes-mcp"]
