FROM node:20-alpine AS build

WORKDIR /workspace

COPY apps/frontend/package*.json ./
RUN npm ci

COPY apps/frontend ./

ARG VITE_API_BASE_URL=/api/v1
ARG VITE_MAP_TILE_URL=https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
ARG VITE_MAP_ATTRIBUTION=&copy; OpenStreetMap contributors
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_MAP_TILE_URL=${VITE_MAP_TILE_URL}
ENV VITE_MAP_ATTRIBUTION=${VITE_MAP_ATTRIBUTION}

RUN npm run build

FROM nginx:1.27-alpine

COPY deployment/docker/frontend.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/dist /usr/share/nginx/html

EXPOSE 8080
