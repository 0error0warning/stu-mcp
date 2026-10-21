FROM python:3.12-slim-bookworm

ARG STU_UID=10001
ARG STU_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STU_MCP_HOME=/var/lib/stu-mcp/campus \
    STU_CHECKIN_HOME=/var/lib/stu-mcp/checkin \
    STU_MCP_KEY_FILE=/run/secrets/master.key \
    STU_MCP_INTERACTION=disabled \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# noVNC and X11 are optional at runtime. Use distro packages, never a downloaded
# desktop image with a default password or an unauthenticated browser endpoint.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tini socat xvfb xauth x11-utils x11vnc novnc websockify openbox \
    && rm -rf /var/lib/apt/lists/* \
    && test "$STU_UID" -gt 0 && test "$STU_GID" -gt 0 \
    && if ! getent group "$STU_GID" >/dev/null; then groupadd --gid "$STU_GID" stu; fi \
    && useradd --uid "$STU_UID" --gid "$STU_GID" --create-home stu

WORKDIR /opt/stu-mcp
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium \
    && mkdir -p /var/lib/stu-mcp /run/stu-mcp \
    && chown "$STU_UID:$STU_GID" /var/lib/stu-mcp /run/stu-mcp
COPY scripts/docker-entrypoint.sh /usr/local/bin/stu-mcp-entrypoint
RUN chmod 0755 /usr/local/bin/stu-mcp-entrypoint

USER stu
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/stu-mcp-entrypoint"]
CMD ["serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8765", "--auth-token-file", "/run/secrets/http-token"]
