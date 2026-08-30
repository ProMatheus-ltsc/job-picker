/**
 * V5 考生画像对话框（F-11）：学历单选（不限/大专/本科/硕士/博士）+ 意向考区多选
 * 保存即作用于所有轮次强过滤（CHG-02 终版）；一键清除恢复全量
 */
import { useEffect, useState } from 'react';
import { DialogShell } from './DialogShell';
import type { Profile } from '../types';

const DEGREES: Array<Profile['degree']> = ['', '大专', '本科', '硕士', '博士'];

interface Props {
  open: boolean;
  profile: Profile;
  /** 候选考区（当前数据全部考区去重） */
  regions: string[];
  onSave: (p: Profile) => void;
  onClose: () => void;
}

export function ProfileDialog({ open, profile, regions, onSave, onClose }: Props) {
  const [degree, setDegree] = useState<Profile['degree']>(profile.degree);
  const [selected, setSelected] = useState<string[]>(profile.regions);

  // 打开时以当前画像重置草稿
  useEffect(() => {
    if (open) {
      setDegree(profile.degree);
      setSelected(profile.regions);
    }
  }, [open, profile]);

  const toggleRegion = (r: string) =>
    setSelected((prev) => (prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]));

  return (
    <DialogShell
      open={open}
      title="考生画像（强过滤）"
      subtitle="保存后立即作用于所有轮次：仅保留「学历要求 ≤ 考生学历」且「考区 ∈ 意向考区」的岗位（两条件独立生效，未设 = 不限）"
      onClose={onClose}
      footer={
        <>
          <button
            className="jp-btn"
            onClick={() => {
              setDegree('');
              setSelected([]);
              onSave({ degree: '', regions: [] });
            }}
          >
            一键清除（恢复全量）
          </button>
          <button className="jp-btn" onClick={onClose}>
            取消
          </button>
          <button
            className="jp-btn primary"
            onClick={() => {
              onSave({ degree, regions: selected });
              onClose();
            }}
          >
            保存并应用
          </button>
        </>
      }
    >
      <div className="pf-row">
        <b>考生学历</b>
        <div className="profile-degrees" role="radiogroup" aria-label="考生学历">
          {DEGREES.map((d) => (
            <label key={d || 'any'}>
              <input
                type="radio"
                name="profile-degree"
                checked={degree === d}
                onChange={() => setDegree(d)}
              />
              {d || '不限'}
            </label>
          ))}
        </div>
      </div>
      <div className="pf-row">
        <b>意向考区（多选，不选 = 不限）</b>
        {regions.length ? (
          <div className="profile-regions">
            {regions.map((r) => (
              <label key={r}>
                <input
                  type="checkbox"
                  checked={selected.includes(r)}
                  onChange={() => toggleRegion(r)}
                />
                {r}
              </label>
            ))}
          </div>
        ) : (
          <p className="dlg-sub">当前数据没有考区列信息。</p>
        )}
      </div>
    </DialogShell>
  );
}
