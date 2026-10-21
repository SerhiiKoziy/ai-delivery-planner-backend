"""add territory_plans and quantum_runs tables

Revision ID: e7fc0d79a699
Revises: 21d39bab6abd
Create Date: 2026-10-19 15:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7fc0d79a699'
down_revision: Union[str, None] = '21d39bab6abd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "territory_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("solver", sa.String(32), nullable=False),
        sa.Column("balance_by", sa.String(32), nullable=False),
        sa.Column("num_zones", sa.Integer(), nullable=False),
        sa.Column("num_deliveries", sa.Integer(), nullable=False),
        sa.Column("zones", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("total_ms", sa.Float(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_territory_plans_organization_id", "territory_plans", ["organization_id"])

    op.create_table(
        "quantum_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("territory_plan_id", sa.Uuid(), sa.ForeignKey("territory_plans.id"), nullable=False),
        sa.Column("step", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("backend_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("job_id", sa.String(100), nullable=True),
        sa.Column("num_qubits", sa.Integer(), nullable=False),
        sa.Column("num_terms", sa.Integer(), nullable=False),
        sa.Column("qaoa_reps", sa.Integer(), nullable=False),
        sa.Column("shots", sa.Integer(), nullable=False),
        sa.Column("logical_depth", sa.Integer(), nullable=True),
        sa.Column("two_qubit_gates", sa.Integer(), nullable=True),
        sa.Column("transpiled_depth", sa.Integer(), nullable=True),
        sa.Column("transpiled_two_qubit_gates", sa.Integer(), nullable=True),
        sa.Column("optimizer_evaluations", sa.Integer(), nullable=True),
        sa.Column("build_ms", sa.Float(), nullable=True),
        sa.Column("classical_ms", sa.Float(), nullable=True),
        sa.Column("optimize_ms", sa.Float(), nullable=True),
        sa.Column("transpile_ms", sa.Float(), nullable=True),
        sa.Column("queue_ms", sa.Float(), nullable=True),
        sa.Column("execution_ms", sa.Float(), nullable=True),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("qpu_seconds", sa.Float(), nullable=True),
        sa.Column("expected_energy", sa.Float(), nullable=True),
        sa.Column("best_energy", sa.Float(), nullable=True),
        sa.Column("optimal_energy", sa.Float(), nullable=True),
        sa.Column("approximation_ratio", sa.Float(), nullable=True),
        sa.Column("optimum_probability", sa.Float(), nullable=True),
        sa.Column("sampled_optimum_frequency", sa.Float(), nullable=True),
        sa.Column("unique_bitstrings", sa.Integer(), nullable=True),
        sa.Column("chosen_source", sa.String(16), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_quantum_runs_territory_plan_id", "quantum_runs", ["territory_plan_id"])
    op.create_index(
        "ix_quantum_runs_organization_id_created_at", "quantum_runs", ["organization_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_quantum_runs_organization_id_created_at", table_name="quantum_runs")
    op.drop_index("ix_quantum_runs_territory_plan_id", table_name="quantum_runs")
    op.drop_table("quantum_runs")
    op.drop_index("ix_territory_plans_organization_id", table_name="territory_plans")
    op.drop_table("territory_plans")
