# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
# Copy frontend source and package files
COPY webui/frontend/package*.json ./
COPY webui/frontend/tsconfig*.json ./
COPY webui/frontend/vite.config.ts ./
COPY webui/frontend/tailwind.config.js ./
COPY webui/frontend/postcss.config.js ./
COPY webui/frontend/index.html ./
COPY webui/frontend/src ./src
# Install dependencies
RUN npm ci
# Build frontend
RUN npm run build

# Stage 2: Build documentation
FROM node:20-alpine AS docs-builder
WORKDIR /app
# Copy docs source and package files
COPY docs/package*.json ./
COPY docs/tsconfig*.json ./
COPY docs/vite.config.ts ./
COPY docs/tailwind.config.js ./
COPY docs/postcss.config.js ./
COPY docs/index.html ./
COPY docs/src ./src
COPY docs/public ./public
COPY docs/scripts ./scripts
COPY docs/eslint.config.js ./
# Install dependencies
RUN npm ci
# Build documentation
RUN npm run build

# Stage 3: Final nginx image
FROM nginx:alpine

# Copy built frontend from frontend builder stage
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# Copy built documentation from docs builder stage
COPY --from=docs-builder /app/dist /usr/share/nginx/html/docs

# Copy Nginx configuration
COPY webui/docker/webui/nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Nginx will start automatically

