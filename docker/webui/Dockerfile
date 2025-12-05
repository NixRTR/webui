FROM nginx:alpine

# Copy frontend build artifacts
# Note: Build context should be set to webui root directory
COPY frontend/dist /usr/share/nginx/html

# Copy docs build artifacts (if available)
COPY docs/dist /usr/share/nginx/html/docs

# Copy Nginx configuration
COPY docker/webui/nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Nginx will start automatically

