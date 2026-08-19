# Widget CDN origin: builds the content-hashed bundle, then ships it on a hardened nginx.
# Kept separate from the API image so a traffic spike on tenant sites never shares compute
# with dashboards or the ingestion pipeline.

FROM node:22-alpine AS build
WORKDIR /build
COPY frontend/apps/widget/package.json ./package.json
COPY frontend/apps/widget/build.mjs ./build.mjs
COPY frontend/apps/widget/src ./src
RUN node build.mjs


FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

USER root
COPY infra/docker/widget-nginx/nginx.conf /etc/nginx/nginx.conf
COPY infra/docker/widget-nginx/widget-headers.conf /etc/nginx/widget-headers.conf
COPY --from=build /build/dist /usr/share/nginx/html/widget
RUN chown -R nginx:nginx /usr/share/nginx/html

# Validate as the runtime user: testing as root leaves root-owned pid/temp files behind in
# /tmp, which then makes the unprivileged startup fail with EACCES. Numeric, because a kubelet
# enforcing runAsNonRoot rejects a user given by name.
USER 101:101
RUN nginx -t -c /etc/nginx/nginx.conf && rm -f /tmp/nginx.pid

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
