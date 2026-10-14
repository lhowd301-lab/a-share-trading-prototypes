"""
position_sizing.py — 仓位分配模型

数学模型（不是拍脑袋）：
  给定当前价格 P、持仓 H、均价 C、现金 R，
  买入 X 股后的新均价:  C_new = (H*C + X*P) / (H + X)
  成本降幅:              ΔC = C - C_new

模型回答两个问题：
  1. 多少钱？  → 基于目标成本的阶段分解
  2. 什么比例？ → 信号强度 × 成本差距 × 剩余预算 的联合函数
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np
from config import (
    HOLDING_SHARES, AVG_COST, AVAILABLE_CASH,
    MAX_BUY_SHARES_PER_MIN, MAX_DAILY_BUY_SHARES, MIN_TRADE_LOT,
)


# ═════════════════════════════════════════════════════════════════════════════
#  1. 核心数学 — CostMath
# ═════════════════════════════════════════════════════════════════════════════

class CostMath:
    """持仓成本数学（纯函数，无副作用）"""

    @staticmethod
    def new_avg_cost(H: int, C: float, X: int, P: float) -> float:
        """买入 X 股 @ P 后的新均价"""
        if X <= 0:
            return C
        return (H * C + X * P) / (H + X)

    @staticmethod
    def shares_to_target(H: int, C: float, target: float, P: float) -> int:
        """在价格 P 买入，将成本从 C 拉到 target 所需的股数

        公式:  target = (H*C + X*P) / (H + X)
        →  X = H * (C - target) / (target - P)
        """
        if target <= P:
            return 0  # 买入价高于目标价，无法降低
        numerator = H * (C - target)
        denominator = target - P
        if denominator <= 0:
            return 0
        X = numerator / denominator
        return int(np.ceil(X / MIN_TRADE_LOT) * MIN_TRADE_LOT)

    @staticmethod
    def cost_reduction(H: int, C: float, X: int, P: float) -> float:
        """买入 X 股 @ P 能降低多少成本（元/股）"""
        if X <= 0:
            return 0.0
        return C - CostMath.new_avg_cost(H, C, X, P)

    @staticmethod
    def cost_gap_ratio(C: float, P: float) -> float:
        """成本与现价的差距比 — 衡量"摊薄杠杆"

        值越大，说明每 1 元买入带来的成本摊薄效果越强
        gap_ratio = (C - P) / C
        """
        return (C - P) / C if C > 0 else 0

    @staticmethod
    def marginal_impact(H: int, C: float, P: float) -> float:
        """每股边际降本效果（元/股）

        买入 1 股 @ P 能降低的成本 ≈ (C - P) / H  （当 X ≪ H 时）
        越大越好
        """
        return (C - P) / H if H > 0 else 0


# ═════════════════════════════════════════════════════════════════════════════
#  2. 成本阶段管理 — StageManager
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class CostStage:
    """一个成本降低阶段"""
    label: str
    target_cost: float          # 本阶段目标成本
    priority: int               # 优先级（数字越小越优先）
    max_allocation_pct: float   # 本阶段最多消耗可用资金的比例 (0~1)

    @property
    def cost_reduction_needed(self) -> float:
        return 0  # 占位，实际计算看上下文


STAGES_DEFAULT = [
    CostStage("Stage-1: 快速降本",  target_cost=90,  priority=1, max_allocation_pct=0.20),
    CostStage("Stage-2: 巩固",      target_cost=86,  priority=2, max_allocation_pct=0.25),
    CostStage("Stage-3: 深入",      target_cost=82,  priority=3, max_allocation_pct=0.30),
    CostStage("Stage-4: 抄底",      target_cost=78,  priority=4, max_allocation_pct=0.25),
]


class StageManager:
    """管理成本降低的阶段演进

    阶段是"软"的：不强制等待某阶段完成，而是根据当前成本和价格
    动态决定应该把资金分配在哪个阶段。
    """

    def __init__(self, stages: Optional[List[CostStage]] = None):
        self.stages = stages or STAGES_DEFAULT
        self._stage_index = 0

    @property
    def current_stage(self) -> CostStage:
        return self.stages[min(self._stage_index, len(self.stages) - 1)]

    def get_active_stages(self, current_cost: float) -> List[CostStage]:
        """返回当前还有效的阶段（目标成本 < 当前成本）"""
        return [s for s in self.stages if s.target_cost < current_cost]

    def advance(self, current_cost: float):
        """如果当前成本已低于当前阶段的目标，推进到下一阶段"""
        while (self._stage_index < len(self.stages)
               and current_cost <= self.stages[self._stage_index].target_cost):
            self._stage_index += 1

    def shares_needed_for_stage(
        self, stage: CostStage, H: int, C: float, P: float
    ) -> int:
        """在本阶段，于价格 P 处还需要买多少股才能达到目标成本"""
        return CostMath.shares_to_target(H, C, stage.target_cost, P)

    def cash_budget_for_stage(self, remaining_cash: float) -> float:
        """本阶段可动用的现金上限"""
        return remaining_cash * self.current_stage.max_allocation_pct


# ═════════════════════════════════════════════════════════════════════════════
#  3. 分配函数 — AllocationFunction
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class AllocationResult:
    """一次分配计算的完整输出"""
    shares: int                     # 建议买入股数
    lots: int                       # 手数
    cost: float                     # 买入总金额
    new_avg_cost: float             # 买入后的新均价
    cost_reduction: float           # 成本降幅（元/股）
    remaining_cash: float           # 剩余现金
    remaining_budget_pct: float     # 剩余预算占比
    allocation_ratio: float         # 本次分配占剩余现金的比例
    signal_strength: float          # 信号强度
    reason: str                     # 分配理由

    def summary(self) -> str:
        return (
            f"┌─ 分配建议 {'─'*40}\n"
            f"│ 买入 {self.shares} 股（{self.lots} 手）= ¥{self.cost:,.0f}\n"
            f"│ 均价: {self.new_avg_cost:.2f}（降 {self.cost_reduction:.2f}）\n"
            f"│ 耗资占剩余 {self.allocation_ratio*100:.1f}%\n"
            f"│ 理由: {self.reason}\n"
            f"└{'─'*48}"
        )


class AllocationModel:
    """仓位分配模型 — 核心

    模型函数:
        A(P, S, state) = min(cash_bound, daily_bound, strategic_bound)

        其中 strategic_bound 由阶段管理器 + 信号强度联合给出。
    """

    def __init__(
        self,
        H: int = HOLDING_SHARES,
        C: float = AVG_COST,
        R: float = AVAILABLE_CASH,
        stage_manager: Optional[StageManager] = None,
    ):
        self.H = H                # 当前持仓股数（动态更新）
        self.C = C                # 当前均价（动态更新）
        self.R = R                # 当前可用现金（动态更新）
        self.R0 = R               # 初始现金
        self.stage = stage_manager or StageManager()
        self._daily_bought = 0    # 日内累计

    def reset_daily(self):
        self._daily_bought = 0

    # ── 核心分配函数 ──────────────────────────────────────────────────────

    def allocate(
        self,
        price: float,
        signal_strength: float,
        boll_width: float = 5.0,
        rsi: float = 50.0,
        verbose: bool = True,
    ) -> AllocationResult:
        """给定当前市况，返回分配建议"""
        P = price
        S = signal_strength
        C, H, R = self.C, self.H, self.R

        # ── Step 1: 更新阶段 ──
        self.stage.advance(C)
        active = self.stage.get_active_stages(C)
        if not active:
            return AllocationResult(0, 0, 0, C, 0, R, 0, 0.0, S, "无有效阶段（均价已足够低）")

        # ── Step 2: 计算战略约束（阶段目标导向） ──
        stage = self.stage.current_stage
        shares_to_target = self.stage.shares_needed_for_stage(stage, H, C, P)
        cash_for_stage = self.stage.cash_budget_for_stage(R)

        # ── Step 3: 信号强度 → 本次分配系数 φ(S) ──
        # sigmoid-like: 弱信号少量参与，强信号大胆介入
        phi = self._signal_to_phi(S)
        # 强度附带解释
        strength_label = self._strength_label(S)

        # ── Step 4: 成本差距放大器 ──
        gap = CostMath.cost_gap_ratio(C, P)
        # gap 约 0.31（现价 65，成本 95），差距越大越该买
        gap_multiplier = 1.0 + gap * 0.5  # gap=0.31 → 1.155
        clip_gap = min(gap_multiplier, 1.5)

        # ── Step 5: 剩余预算衰减因子 ψ ──
        # 资金越少越谨慎
        budget_ratio = R / self.R0
        psi = 0.3 + 0.7 * budget_ratio  # 资金充裕时 ≈1.0，快花完时 ≈0.3

        # ── Step 6: 计算建议买入量 ──
        # 战略参考量 = 达到阶段目标所需股数 × φ × gap_multiplier
        strategic_ref = shares_to_target * phi * clip_gap

        # 现金约束 = 阶段预算 / 价格
        cash_bound = int(cash_for_stage / P) if P > 0 else 0
        # 日限额约束
        daily_remaining = MAX_DAILY_BUY_SHARES - self._daily_bought
        daily_bound = min(MAX_BUY_SHARES_PER_MIN, daily_remaining)
        # 成交额软约束（防止冲击）
        volume_bound = daily_bound

        # 最终：三约束取最小，然后对齐到手数
        target = min(strategic_ref, cash_bound, volume_bound)
        target = max(int(target // MIN_TRADE_LOT) * MIN_TRADE_LOT, 0)
        target = min(target, MAX_DAILY_BUY_SHARES - self._daily_bought)

        # 如果目标 < 1 手，放弃
        if target < MIN_TRADE_LOT:
            return AllocationResult(0, 0, 0, C, 0, R, 0, 0.0, S, "计算量不足 1 手")

        # ── Step 7: 计算买入后影响 ──
        new_cost = CostMath.new_avg_cost(H, C, target, P)
        reduction = C - new_cost
        cost_amount = target * P

        # 实际分配比例
        alloc_ratio = cost_amount / R if R > 0 else 0

        # ── Step 8: 生成理由 ──
        reason = (
            f"{stage.label} | {strength_label} "
            f"| 差距放大 {clip_gap:.2f}x | 预算因子 {psi:.2f}"
        )

        return AllocationResult(
            shares=target,
            lots=target // 100,
            cost=round(cost_amount, 2),
            new_avg_cost=round(new_cost, 3),
            cost_reduction=round(reduction, 3),
            remaining_cash=round(R - cost_amount, 2),
            remaining_budget_pct=round((R - cost_amount) / self.R0 * 100, 1),
            allocation_ratio=round(alloc_ratio, 4),
            signal_strength=round(S, 2),
            reason=reason,
        )

    def commit(self, result: AllocationResult, price: float):
        """执行分配后更新内部状态"""
        self.H += result.shares
        self.C = result.new_avg_cost
        self.R = result.remaining_cash
        self._daily_bought += result.shares
        self.stage.advance(self.C)

    # ── 信号转系数 ────────────────────────────────────────────────────────

    @staticmethod
    def _signal_to_phi(S: float) -> float:
        """信号强度 → 分配系数 φ

        字号映射:
          探 = 0.12  (5千股级别)
          轻 = 0.22  (1万股级别)
          中 = 0.33  (1.5万股级别)
          重 = 0.44  (2万股级别)
        """
        if S < 0.35:
            return 0.0
        elif S < 0.50:
            return 0.12
        elif S < 0.70:
            return 0.22
        elif S < 0.80:
            return 0.33
        else:
            return 0.44

    @staticmethod
    def _strength_label(S: float) -> str:
        if S >= 0.80:
            return "重"
        elif S >= 0.70:
            return "中"
        elif S >= 0.50:
            return "轻"
        elif S >= 0.35:
            return "探"
        return "不买"

    # ── 情景分析 ──────────────────────────────────────────────────────────

    def scenario_table(self, price_range: Tuple[float, float, float],
                       signal_strengths: List[float]) -> str:
        """生成情景分析表

        price_range: (min, max, step)
        signal_strengths: 要测试的信号强度列表
        """
        p_min, p_max, p_step = price_range
        prices = np.arange(p_min, p_max + p_step, p_step)

        lines = []
        lines.append(f"{'当前价':>8}  {'信号强度':>8}  {'建议股数':>10}  {'新均价':>8}  {'降幅':>8}  {'耗资':>10}  {'占比':>6}")
        lines.append("-" * 80)

        for P in prices:
            for S in signal_strengths:
                # 临时模型（不修改状态）
                temp = AllocationModel(self.H, self.C, self.R, self.stage)
                result = temp.allocate(P, S, verbose=False)
                if result.shares > 0:
                    pct = result.cost / self.R * 100 if self.R > 0 else 0
                    lines.append(
                        f"{P:>8.2f}  {S:>8.2f}  {result.shares:>10}  "
                        f"{result.new_avg_cost:>8.2f}  {result.cost_reduction:>8.3f}  "
                        f"{result.cost:>10,.0f}  {pct:>5.1f}%"
                    )
                else:
                    lines.append(f"{P:>8.2f}  {S:>8.2f}  {'—':>10}  {'—':>8}  {'—':>8}  {'—':>10}  {'—':>6}")

        return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
#  4. 快速测试
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("仓位分配模型测试")
    print(f"持仓 {HOLDING_SHARES} 股 @ {AVG_COST}")
    print(f"可用 {AVAILABLE_CASH:,} 元")
    print("=" * 60)

    model = AllocationModel()
    # 模拟不同价格、不同信号强度下的分配结果
    for price in [68, 66, 64, 62]:
        for strength in [0.35, 0.55, 0.75]:
            result = model.allocate(price, strength, verbose=False)
            if result.shares > 0:
                print(f"\n价格 {price:.0f}  强度 {strength:.2f}")
                print(f"  → {result.shares} 股, 新均价 {result.new_avg_cost:.2f}, "
                      f"降 {result.cost_reduction:.3f}, 耗资 {result.cost:,.0f}")
                print(f"  理由: {result.reason}")
            else:
                print(f"\n价格 {price:.0f} 强度 {strength:.2f} → 不分配")

    # 情景分析表
    print("\n\n情景分析（不同价格 × 信号强度）：")
    print(model.scenario_table((62, 70, 2), [0.3, 0.5, 0.7]))
