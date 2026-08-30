// @shared/core standard 模式接入（04 §7.1，README「引用方式（标准模式）」为权威来源）：
// - package.json: "@shared/core": "file:../shared-core"（本地 junction；CI 内 clone + checkout 971b3e6）
// - vite alias '@shared/core' → ../shared-core/src（主入口）
// - '@shared/core/<子路径>' 按上游 exports 映射（services/db / styles/responsive.css）
// - resolve.dedupe 防 production 双 React 白屏（dev/typecheck 均不报错，必须 preview 实测，04 §8 R7）
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';

const sharedSrc = fileURLToPath(new URL('../shared-core/src', import.meta.url));

export default defineConfig({
  base: '/job-picker/',
  plugins: [react(), tailwindcss()],
  resolve: {
    // 防双 React：共享包（../shared-core）自身 node_modules 含 react 副本，
    // 不 dedupe 时 production 打包出两份 React → hooks 运行时崩溃白屏
    dedupe: ['react', 'react-dom', 'react-router', 'react-router-dom', 'react-hook-form'],
    alias: [
      { find: /^@shared\/core$/, replacement: `${sharedSrc}/index.ts` },
      { find: /^@shared\/core\/(.+)$/, replacement: `${sharedSrc}/$1` },
    ],
  },
  build: {
    // xlsx 较大，单独分块（04 §8 R4：不进首屏，导入时动态加载）
    rollupOptions: {
      output: {
        manualChunks: {
          xlsx: ['xlsx'],
        },
      },
    },
  },
});
