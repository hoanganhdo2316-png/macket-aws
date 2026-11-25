FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY admin/ ./admin/
COPY src/ ./src/
RUN npm run build

FROM nginx:stable-alpine
RUN apk add --no-cache 'zlib>=1.4-r0'
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
EXPOSE 80
