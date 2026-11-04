#!/usr/bin/env tsx
/**
 * 引擎探针：把 `engine/` 的纯函数暴露成一条 JSON-in / JSON-out 的命令行，
 * 供 Python 侧 pytest 做断言（项目统一测试入口是 `python -m pytest -q`）。
 *
 * 用法：
 *   echo '{"region":"广州市南沙区发展和改革局"}' | npx tsx tests/ts/probe.ts --op salary
 *   npx tsx tests/ts/probe.ts --op intensity --file job.json
 *
 * 只做转发与序列化，不含任何业务判定——判定逻辑一律在 engine/ 里，避免测试与实现各写一份。
 */
import { readFileSync } from 'node:fs';
import { estimateSalary, salaryLabel, salaryMidpoint } from '../../engine/core/salary';
import { scanIntensity, intensitySummary } from '../../engine/core/intensity';
import { estimateProbability, formatProbability } from '../../engine/core/probability';
import { nonDominated, paretoSummary } from '../../engine/core/pareto';
import { renderScopeNotice } from '../../engine/core/scope';
import { requireUsable, annotate, canUse, weakest, GRADES } from '../../engine/core/datagrade';
import { parseExamType, minServiceYears, hasLongServiceBond, cutoffGrade } from '../../engine/core/examMode';
import { renderScatterHtml } from '../../engine/io/scatter';
import { renderMarkdownReport } from '../../engine/io/markdownReport';

function readInput(): Record<string, unknown> {
  const fileIndex = process.argv.indexOf('--file');
  const text = fileIndex > -1 && process.argv[fileIndex + 1]
    ? readFileSync(process.argv[fileIndex + 1], 'utf-8')
    : readFileSync(0, 'utf-8');
  const trimmed = (text ?? '').trim();
  return trimmed ? (JSON.parse(trimmed) as Record<string, unknown>) : {};
}

function op(): string {
  const index = process.argv.indexOf('--op');
  return index > -1 && process.argv[index + 1] ? process.argv[index + 1] : '';
}

function fail(code: number, message: string): never {
  process.stdout.write(JSON.stringify({ ok: false, code, error: message }));
  process.exit(code);
}

const input = readInput();
const name = op();

try {
  switch (name) {
    case 'salary': {
      const region = String(input.region ?? '');
      const est = estimateSalary(region);
      const table = (input.regions as string[] | undefined)?.map((r) => {
        const s = estimateSalary(r);
        return {
          region: r,
          city: s.city,
          district: s.district,
          label: salaryLabel(s),
          payMin: s.payMin,
          payMax: s.payMax,
          mid: salaryMidpoint(s),
          precise: s.precise,
        };
      });
      process.stdout.write(
        JSON.stringify({
          ok: true,
          city: est.city,
          district: est.district,
          label: salaryLabel(est),
          payMin: est.payMin,
          payMax: est.payMax,
          mid: salaryMidpoint(est),
          precise: est.precise,
          basis: est.basis,
          table,
        }),
      );
      break;
    }
    case 'intensity': {
      const job = (input.job ?? input) as Parameters<typeof scanIntensity>[0];
      const result = scanIntensity(job, input.lexicon as Parameters<typeof scanIntensity>[1]);
      process.stdout.write(
        JSON.stringify({ ok: true, ...result, summary: intensitySummary(result) }),
      );
      break;
    }
    case 'probability': {
      const result = estimateProbability(input as Parameters<typeof estimateProbability>[0]);
      process.stdout.write(
        JSON.stringify({
          ok: true,
          ...result,
          display: formatProbability(result.p),
          cutoffGrade: result.cutoffGraded?.grade ?? null,
        }),
      );
      break;
    }
    case 'probability-batch': {
      const items = (input.items ?? []) as Array<Record<string, unknown>>;
      const results = items.map((item) => {
        const r = estimateProbability(item as Parameters<typeof estimateProbability>[0]);
        return { key: item.key, p: r.p, missingInputs: r.missingInputs, quota: r.quota };
      });
      process.stdout.write(JSON.stringify({ ok: true, results }));
      break;
    }
    case 'pareto': {
      const result = nonDominated(
        (input.points ?? []) as Parameters<typeof nonDominated>[0],
      );
      process.stdout.write(JSON.stringify({ ok: true, ...result, summary: paretoSummary(result) }));
      break;
    }
    case 'scope': {
      const text = renderScopeNotice(input as Parameters<typeof renderScopeNotice>[0]);
      process.stdout.write(JSON.stringify({ ok: true, text }));
      break;
    }
    case 'datagrade': {
      const out: Record<string, unknown> = { ok: true };
      if (input.canUse) {
        const { grade, use } = input.canUse as { grade: string; use: string };
        out.canUse = canUse(grade as never, use as never);
      }
      if (input.weakest) {
        out.weakest = weakest(...(input.weakest as never[]));
      }
      if (input.annotate) {
        const { value, grade, source } = input.annotate as Record<string, unknown>;
        out.annotated = annotate(value as number, grade as never, String(source ?? ''));
      }
      if (input.requireUsable) {
        const { value, grade, use, source } = input.requireUsable as Record<string, unknown>;
        try {
          out.graded = requireUsable(
            value as number,
            grade as never,
            use as never,
            String(source ?? ''),
          );
        } catch (error) {
          out.graded = null;
          out.errorName = error instanceof Error ? error.name : 'unknown';
          out.errorMessage = error instanceof Error ? error.message : String(error);
        }
      }
      out.grades = GRADES;
      process.stdout.write(JSON.stringify(out));
      break;
    }
    case 'exammode': {
      const sourceSheet = String(input.sourceSheet ?? '');
      process.stdout.write(
        JSON.stringify({
          ok: true,
          parsed: parseExamType(input.examType as string | null),
          minServiceYears: minServiceYears(sourceSheet),
          hasLongServiceBond: hasLongServiceBond(sourceSheet),
          cutoffGradeSk: cutoffGrade('sk'),
          cutoffGradeGk: cutoffGrade('gk'),
        }),
      );
      break;
    }
    case 'scatter': {
      const html = renderScatterHtml(
        (input.points ?? []) as Parameters<typeof renderScatterHtml>[0],
        String(input.title ?? '薪酬 × 进面概率'),
      );
      // 大文本走独立文件，避免 stdout 过长
      process.stdout.write(JSON.stringify({ ok: true, html }));
      break;
    }
    case 'report': {
      const md = renderMarkdownReport(input as Parameters<typeof renderMarkdownReport>[0]);
      process.stdout.write(JSON.stringify({ ok: true, md }));
      break;
    }
    default:
      fail(2, `未知 --op: ${name || '(空)'}`);
  }
} catch (error) {
  process.stdout.write(
    JSON.stringify({
      ok: false,
      code: 1,
      errorName: error instanceof Error ? error.name : 'unknown',
      errorMessage: error instanceof Error ? error.message : String(error),
    }),
  );
  process.exit(1);
}
