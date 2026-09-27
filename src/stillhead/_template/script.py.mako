<%
    body = "".join([upgrades or "", downgrades or "", imports or ""])
    needs_sqlalchemy = "sa." in body
    needs_op = "op." in body

    def literal(value):
        """Render like ruff format would, so generated files pass the gate.

        repr() emits single quotes; the repo formats to double.
        """
        if value is None:
            return "None"
        if isinstance(value, str):
            return '"{}"'.format(value.replace('"', '\\"'))
        items = [literal(item) for item in value]
        if len(items) == 1:
            return "({},)".format(items[0])
        return "({})".format(", ".join(items))
%>\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from __future__ import annotations
% if needs_sqlalchemy or needs_op:

% endif
% if needs_sqlalchemy:
import sqlalchemy as sa
% endif
% if needs_op:
from alembic import op
% endif
% if imports:
${imports}
% endif

revision: str = ${literal(up_revision)}
down_revision: str | None = ${literal(down_revision)}
branch_labels: tuple[str, ...] | None = ${literal(branch_labels)}
depends_on: tuple[str, ...] | None = ${literal(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
