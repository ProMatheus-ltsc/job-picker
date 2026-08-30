/**
 * V3 筛选栏（F-04）：考区/学历下拉（选项来自当前数据去重值）+ 专业关键词（SearchBar，Q-D6）+ 报名人数区间
 * 区间倒置即时红框提示且不发起筛选（规则 4）
 */
import { SearchBar } from '@shared/core';
import type { Filters } from '../types';

interface Props {
  filters: Filters;
  regions: string[];
  degrees: string[];
  rangeInvalid: boolean;
  onChange: (f: Filters) => void;
}

export function FiltersBar({ filters, regions, degrees, rangeInvalid, onChange }: Props) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });

  return (
    <div className="filters-wrap">
      <div className="fld">
        <label htmlFor="f-region">考区</label>
        <select id="f-region" value={filters.region} onChange={(e) => set({ region: e.target.value })}>
          <option value="">（不限）</option>
          {regions.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <div className="fld">
        <label htmlFor="f-degree">学历要求</label>
        <select id="f-degree" value={filters.degree} onChange={(e) => set({ degree: e.target.value })}>
          <option value="">（不限）</option>
          {degrees.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>
      <div className="fld fld-kw">
        <label htmlFor="f-major">专业关键词（包含匹配，不区分大小写）</label>
        <SearchBar
          value={filters.majorKeyword}
          onChange={(v) => set({ majorKeyword: v })}
          placeholder="输入专业关键词，如：法学"
        />
      </div>
      <div className="fld">
        <label htmlFor="f-apply-min">报名人数区间</label>
        <div className="range2">
          <input
            id="f-apply-min"
            type="number"
            className={rangeInvalid ? 'err' : ''}
            value={filters.applyMin ?? ''}
            placeholder="最小"
            onChange={(e) => set({ applyMin: e.target.value === '' ? null : +e.target.value })}
          />
          <span>~</span>
          <input
            type="number"
            className={rangeInvalid ? 'err' : ''}
            value={filters.applyMax ?? ''}
            placeholder="最大"
            aria-label="报名人数最大值"
            onChange={(e) => set({ applyMax: e.target.value === '' ? null : +e.target.value })}
          />
        </div>
        <div className="fld-err">{rangeInvalid ? '区间倒置：最小值大于最大值' : ''}</div>
      </div>
    </div>
  );
}
