"""Cost of a day with no battery, with a rule, and with the optimiser."""

from pydantic import BaseModel, ConfigDict


class ComparisonReport(BaseModel):
    """How much of the optimiser's saving a simpler rule keeps.

    Savings are the no-battery bill minus that schedule's bill, in pence.
    ``rule_savings_share`` is the rule's saving divided by the optimiser's.
    A share of 1 means the rule matched the optimal bill. When the optimiser
    saves nothing, the share is 1 if the rule matches that bill and 0 if the
    rule costs more.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    no_battery_cost_pence: float
    rule_cost_pence: float
    optimiser_cost_pence: float
    rule_savings_share: float
