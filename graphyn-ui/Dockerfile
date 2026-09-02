FROM node:22-alpine AS build
WORKDIR /ui
COPY graphyn-ui/package.json graphyn-ui/package-lock.json ./
RUN npm ci
COPY graphyn-ui/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY graphyn-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
