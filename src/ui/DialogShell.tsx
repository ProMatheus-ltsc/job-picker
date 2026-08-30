/**
 * V4/V5/V6 自建对话框共用外壳（04 §6.3：根节点挂 modal-clamp 获得视口钳制）
 * - overlay 点击 / Esc 关闭；内容点击不冒泡
 * - role="dialog" aria-modal 基础语义
 */
import { useEffect, type ReactNode } from 'react';

interface Props {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  /** 底部操作区（dlg-actions） */
  footer?: ReactNode;
  width?: number;
}

export function DialogShell({ open, title, subtitle, onClose, children, footer, width = 760 }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="jp-overlay" onClick={onClose}>
      <div
        className="jp-dialog modal-clamp"
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dlg-body">
          <h3 className="dlg-title">{title}</h3>
          {subtitle && <p className="dlg-sub">{subtitle}</p>}
          {children}
          {footer && <div className="dlg-actions">{footer}</div>}
        </div>
      </div>
    </div>
  );
}
