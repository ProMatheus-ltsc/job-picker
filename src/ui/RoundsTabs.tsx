/**
 * V3 轮次 Tab（F-05）：徽标 = 该轮链式基础名单 ∩ 画像过滤后数量（roundList 唯一口径，Q-D9）
 */
import { Plus } from 'lucide-react';

interface Props {
  rounds: string[];
  current: number;
  counts: number[];
  onSelect: (r: number) => void;
  onAdd: () => void;
}

export function RoundsTabs({ rounds, current, counts, onSelect, onAdd }: Props) {
  return (
    <div className="tabs-wrap" role="tablist" aria-label="筛选轮次">
      {rounds.map((name, r) => (
        <button
          key={`${r}-${name}`}
          role="tab"
          aria-selected={r === current}
          className={`round-tab${r === current ? ' on' : ''}`}
          onClick={() => onSelect(r)}
        >
          {name}
          <span className="cnt">{counts[r] ?? 0}</span>
        </button>
      ))}
      <button className="round-tab add" onClick={onAdd} title="新增自定义轮次（追加在现有轮次之后）">
        <Plus size={12} className="mr-0.5 inline align-[-2px]" />
        新增轮次
      </button>
    </div>
  );
}
