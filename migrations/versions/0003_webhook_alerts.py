"""Webhook alerts

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="tradingview"),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("alert_name", sa.String(length=128), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("raw_body", sa.Text(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webhook_alerts_id"), "webhook_alerts", ["id"])
    op.create_index(op.f("ix_webhook_alerts_symbol"), "webhook_alerts", ["symbol"])


def downgrade() -> None:
    op.drop_table("webhook_alerts")
