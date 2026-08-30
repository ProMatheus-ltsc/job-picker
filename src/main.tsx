/**
 * 应用入口 — 启动序列（04 §6.2）：
 * main.css → responsive.css 基线（后置导入覆盖优先级）
 * → initDB（configureDB + setCurrentAccountId，子路径导入）
 * → loadState 读取存量（失败按空状态冷启动）
 * → 按 jobs 有无决定 MemoryRouter initialEntry → 挂载
 */
import './styles/main.css';
import '@shared/core/styles/responsive.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { initDB, loadState } from './core/store';
import { App } from './App';

initDB();

const rootEl = document.getElementById('root')!;
const root = createRoot(rootEl);

loadState().then((result) => {
  // loadState 失败（E_STORAGE_PARSE）按空状态冷启动进 /welcome（不崩溃，F-10 规则 4）
  const initialState = result.ok ? result.data : null;
  root.render(
    <StrictMode>
      <App initialState={initialState} />
    </StrictMode>,
  );
});
