"""Broker credentials and orders

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False, server_default="kite"),
        sa.Column("broker_user_id", sa.String(length=64), nullable=True),
        sa.Column("encrypted_access_token", sa.String(length=512), nullable=False),
        sa.Column("encrypted_public_token", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "broker", name="uq_user_broker"),
    )
    op.create_index(op.f("ix_broker_credentials_id"), "broker_credentials", ["id"])
    op.create_index(
        op.f("ix_broker_credentials_user_id"), "broker_credentials", ["user_id"]
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False, server_default="paper"),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False, server_default="NSE"),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("product", sa.String(length=8), nullable=False, server_default="CNC"),
        sa.Column("order_type", sa.String(length=8), nullable=False, server_default="MARKET"),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("trigger_price", sa.Float(), nullable=True),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "OPEN", "COMPLETE", "CANCELLED", "REJECTED",
                name="order_status", native_enum=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("status_message", sa.String(length=255), nullable=True),
        sa.Column("is_paper", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("target", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # The most important line in this file: a retried request cannot become
        # a second live order.
        sa.UniqueConstraint("idempotency_key", name="uq_order_idempotency_key"),
    )
    op.create_index(op.f("ix_orders_id"), "orders", ["id"])
    op.create_index(op.f("ix_orders_user_id"), "orders", ["user_id"])
    op.create_index(op.f("ix_orders_symbol"), "orders", ["symbol"])
    op.create_index(op.f("ix_orders_status"), "orders", ["status"])
    op.create_index(op.f("ix_orders_idempotency_key"), "orders", ["idempotency_key"])
    op.create_index(op.f("ix_orders_broker_order_id"), "orders", ["broker_order_id"])


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("broker_credentials")
