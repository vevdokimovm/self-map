import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Локальный инструмент над данными этого же репозитория. Без бэкенда,
// без деплоя, без внешних сетевых вызовов: `npm run dev`, данные читаются
// с диска в public/data (см. scripts/sync-data.mjs), ничего никуда не уходит.
export default defineConfig({
  plugins: [react()],
  server: { port: 5185 },
});
