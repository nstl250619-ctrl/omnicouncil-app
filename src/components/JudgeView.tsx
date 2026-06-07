import { useAppStore } from '../stores/appStore';

interface JudgeVerdict {
  conflictTopic: string;
  confidence: number;
  recommendedPosition: string;
  reasoning: string;
  evidence: string;
}

interface JudgeViewProps {
  verdicts?: JudgeVerdict[];
}

// Mock data for when backend doesn't have judge results yet
const MOCK_VERDICTS: JudgeVerdict[] = [
  {
    conflictTopic: '量子纠缠与超光速通信',
    confidence: 92,
    recommendedPosition: '支持 ChatGPT / MiMo 的观点',
    reasoning:
      '根据当前物理学共识，量子纠缠不能用于超光速信息传递。不可克隆定理和贝尔不等式的实验验证表明，虽然纠缠态具有非定域关联，但无法利用这种关联传递可控信息。',
    evidence:
      '评判依据：不可克隆定理（Wootters-Zurek, 1982）、no-communication theorem 的严格证明。该结论在物理学界具有高度共识。',
  },
  {
    conflictTopic: '量子计算商业化时间线',
    confidence: 65,
    recommendedPosition: '倾向保守派，但保留开放态度',
    reasoning:
      '考虑到量子纠错的实际开销，10-15 年的时间线更为现实。但特定领域的量子优势可能在更短时间内实现。',
    evidence:
      '评判依据：IBM 和 Google 的最新路线图、Nature Reviews Physics 2024 年综述。此议题存在不确定性，置信度较低。',
  },
];

export function JudgeView({ verdicts }: JudgeViewProps) {
  const conflict = useAppStore((s) => s.conflict);
  const data = verdicts || MOCK_VERDICTS;

  // Show empty state if no conflict data and no verdicts
  if (!conflict && !verdicts) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🏛</div>
        <div className="empty-title">暂无评判数据</div>
        <div className="empty-desc">系统将对冲突进行评判，给出更合理的立场建议</div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 780 }}>
      <div style={{ marginBottom: 24 }}>
        <div
          style={{
            fontFamily: "'Syne', sans-serif",
            fontWeight: 700,
            fontSize: 18,
            marginBottom: 6,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          🏛 评判建议
        </div>
        <div
          style={{
            fontFamily: "'Source Serif 4', serif",
            fontSize: 13,
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
          }}
        >
          基于冲突分析结果，对每个冲突议题给出推荐立场、评判依据和理由。
        </div>
      </div>

      {data.map((verdict, i) => (
        <div
          key={i}
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 10,
            padding: 18,
            borderLeft: '3px solid var(--accent)',
            marginBottom: 12,
          }}
        >
          {/* Header: topic + confidence */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: 10,
            }}
          >
            <div
              style={{
                fontFamily: "'Syne', sans-serif",
                fontWeight: 600,
                fontSize: 14,
              }}
            >
              {verdict.conflictTopic}
            </div>
            <div
              style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 12,
                color: 'var(--accent)',
              }}
            >
              置信度: {verdict.confidence}%
            </div>
          </div>

          {/* Body: recommended position + reasoning */}
          <div
            style={{
              fontFamily: "'Source Serif 4', serif",
              fontSize: 13.5,
              color: 'var(--text-secondary)',
              lineHeight: 1.7,
              marginBottom: 10,
            }}
          >
            <strong>推荐立场：{verdict.recommendedPosition}</strong>
            <br />
            {verdict.reasoning}
          </div>

          {/* Footer: evidence */}
          <div
            style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: 11,
              color: 'var(--text-muted)',
              padding: '10px 14px',
              background: 'var(--bg-inset)',
              borderRadius: 6,
              lineHeight: 1.6,
            }}
          >
            {verdict.evidence}
          </div>
        </div>
      ))}
    </div>
  );
}
