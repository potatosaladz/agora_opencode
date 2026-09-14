"""Expand with the tenant-scoped Phase 3 session and artifact schema.

Revision ID: 20260905_0005
Revises: 20260905_0004
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0005"
down_revision: str | None = "20260905_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = (
    "sessions",
    "session_agents",
    "reasoning_artifacts",
    "session_objectives",
    "session_constraints",
)


# trace: FR-303, FR-312
def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_workspace_isolation ON {table} "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = "
        "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def _create_json_validation_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION jsonb_has_exact_keys(
          document jsonb,
          required_keys text[],
          optional_keys text[] DEFAULT ARRAY[]::text[]
        ) RETURNS boolean AS $$
        BEGIN
          IF jsonb_typeof(document) <> 'object' THEN
            RETURN false;
          END IF;
          RETURN NOT EXISTS (
            SELECT 1 FROM unnest(required_keys) AS required_key
            WHERE NOT document ? required_key
          ) AND NOT EXISTS (
            SELECT 1 FROM jsonb_object_keys(document) AS actual_key
            WHERE NOT actual_key = ANY(required_keys || optional_keys)
          );
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION jsonb_nonempty_text(document jsonb, key_name text) RETURNS boolean AS $$
          SELECT jsonb_typeof(document -> key_name) = 'string'
            AND length(btrim(document ->> key_name)) > 0;
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION jsonb_uuid_text(value jsonb) RETURNS boolean AS $$
          SELECT jsonb_typeof(value) = 'string'
            AND (value #>> '{}') ~
              '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$';
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION jsonb_all_uuid_texts(value jsonb) RETURNS boolean AS $$
        BEGIN
          IF jsonb_typeof(value) <> 'array' THEN
            RETURN false;
          END IF;
          RETURN NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(value) AS item
            WHERE NOT jsonb_uuid_text(item)
          );
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION jsonb_all_nonempty_texts(value jsonb) RETURNS boolean AS $$
        BEGIN
          IF jsonb_typeof(value) <> 'array' THEN
            RETURN false;
          END IF;
          RETURN NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(value) AS item
            WHERE jsonb_typeof(item) <> 'string' OR length(btrim(item #>> '{}')) = 0
          );
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION jsonb_decimal_string(value jsonb) RETURNS boolean AS $$
          SELECT jsonb_typeof(value) = 'string'
            AND (value #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]*[1-9])?$'
            AND (value #>> '{}') <> '-0';
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION jsonb_unit_decimal_string(value jsonb) RETURNS boolean AS $$
        BEGIN
          IF NOT jsonb_decimal_string(value) THEN
            RETURN false;
          END IF;
          RETURN (value #>> '{}')::numeric BETWEEN 0 AND 1;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """
    )


def _create_payload_validation_function() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_reasoning_artifact_payload(kind_value text, body jsonb)
        RETURNS boolean AS $$
        DECLARE
          scenario jsonb;
          expression jsonb;
        BEGIN
          IF jsonb_typeof(body) <> 'object' THEN
            RETURN false;
          END IF;

          CASE kind_value
            WHEN 'CLAIM' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY[
                  'statement', 'claim_type', 'direction', 'strength',
                  'supporting_evidence_ids', 'opposing_evidence_ids', 'review_status'
                ])
                AND jsonb_nonempty_text(body, 'statement')
                AND body ->> 'claim_type' IN
                  ('FACTUAL','CAUSAL','PREDICTIVE','EVALUATIVE','PROCEDURAL','HYPOTHESIS')
                AND body ->> 'direction' IN ('SUPPORTS','OPPOSES')
                AND body ->> 'strength' IN ('WEAK','MODERATE','STRONG','DECISIVE')
                AND jsonb_all_uuid_texts(body -> 'supporting_evidence_ids')
                AND jsonb_all_uuid_texts(body -> 'opposing_evidence_ids')
                AND body ->> 'review_status' IN ('PROPOSED','ACCEPTED','CONTESTED','REJECTED'),
                false
              );
            WHEN 'FACT' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY['statement','verification'])
                AND jsonb_nonempty_text(body, 'statement')
                AND body ->> 'verification' IN ('SOURCE_VERIFIED','CROSS_CHECKED'),
                false
              );
            WHEN 'ASSUMPTION' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(
                  body, ARRAY['statement','basis','materiality','challengeable']
                )
                AND jsonb_nonempty_text(body, 'statement')
                AND jsonb_nonempty_text(body, 'basis')
                AND jsonb_nonempty_text(body, 'materiality')
                AND jsonb_typeof(body -> 'challengeable') = 'boolean',
                false
              );
            WHEN 'INFERENCE' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(
                  body, ARRAY['premise_ids','conclusion_id','rule_kind','rule_text','validity']
                )
                AND jsonb_all_uuid_texts(body -> 'premise_ids')
                AND jsonb_uuid_text(body -> 'conclusion_id')
                AND jsonb_nonempty_text(body, 'rule_kind')
                AND jsonb_nonempty_text(body, 'rule_text')
                AND jsonb_nonempty_text(body, 'validity'),
                false
              );
            WHEN 'PROPOSITION' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY[
                  'statement_original', 'statement_normalized', 'canonicalizer_version',
                  'proposition_kind', 'modality', 'normalization_status'
                ])
                AND jsonb_nonempty_text(body, 'statement_original')
                AND jsonb_nonempty_text(body, 'statement_normalized')
                AND jsonb_nonempty_text(body, 'canonicalizer_version')
                AND jsonb_nonempty_text(body, 'proposition_kind')
                AND jsonb_nonempty_text(body, 'modality')
                AND body ->> 'normalization_status' IN ('PROPOSED','VALIDATED','AMBIGUOUS'),
                false
              );
            WHEN 'EVIDENCE' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY[
                  'claim_id', 'relation', 'quote', 'verification', 'trust_level', 'weight',
                  'provenance_kind'
                ])
                AND jsonb_uuid_text(body -> 'claim_id')
                AND body ->> 'relation' IN ('SUPPORTS','OPPOSES','QUALIFIES')
                AND jsonb_nonempty_text(body, 'quote')
                AND body ->> 'verification' IN
                  ('UNVERIFIED','SOURCE_VERIFIED','CROSS_CHECKED','DISPUTED','REJECTED')
                AND body ->> 'trust_level' IN
                  ('PRIMARY','AUTHORITATIVE','SECONDARY','COMMERCIAL')
                AND jsonb_unit_decimal_string(body -> 'weight')
                AND body ->> 'provenance_kind' IN
                  ('RETRIEVAL','TOOL','SIMULATION','SYMBOLIC','HUMAN','IMPORT'),
                false
              );
            WHEN 'UNCERTAINTY' THEN
              IF body ->> 'uncertainty_type' NOT IN
                ('EPISTEMIC','ALEATORIC','MODEL','MEASUREMENT','SEMANTIC','STRATEGIC')
                OR NOT jsonb_uuid_text(body -> 'target_id')
                OR NOT jsonb_all_nonempty_texts(body -> 'drivers') THEN
                RETURN false;
              END IF;
              CASE body ->> 'representation'
                WHEN 'INTERVAL' THEN
                  IF NOT jsonb_has_exact_keys(body, ARRAY[
                    'target_id','uncertainty_type','representation','drivers','lower','upper','unit'
                  ])
                    OR NOT jsonb_decimal_string(body -> 'lower')
                    OR NOT jsonb_decimal_string(body -> 'upper')
                    OR NOT jsonb_nonempty_text(body, 'unit') THEN
                    RETURN false;
                  END IF;
                  RETURN (body ->> 'lower')::numeric <= (body ->> 'upper')::numeric;
                WHEN 'DISTRIBUTION' THEN
                  RETURN COALESCE(
                    jsonb_has_exact_keys(body, ARRAY[
                      'target_id','uncertainty_type','representation','drivers',
                      'family','parameters','unit'
                    ])
                    AND jsonb_nonempty_text(body, 'family')
                    AND jsonb_typeof(body -> 'parameters') = 'object'
                    AND jsonb_nonempty_text(body, 'unit'),
                    false
                  );
                WHEN 'SCENARIOS' THEN
                  IF NOT jsonb_has_exact_keys(body, ARRAY[
                    'target_id','uncertainty_type','representation','drivers','scenarios'
                  ]) OR jsonb_typeof(body -> 'scenarios') <> 'array'
                    OR jsonb_array_length(body -> 'scenarios') = 0 THEN
                    RETURN false;
                  END IF;
                  FOR scenario IN SELECT value FROM jsonb_array_elements(body -> 'scenarios') LOOP
                    IF NOT COALESCE(
                      jsonb_has_exact_keys(scenario, ARRAY['name','probability','value'])
                      AND jsonb_nonempty_text(scenario, 'name')
                      AND jsonb_unit_decimal_string(scenario -> 'probability'), false
                    ) THEN
                      RETURN false;
                    END IF;
                  END LOOP;
                  RETURN true;
                WHEN 'QUALITATIVE' THEN
                  RETURN COALESCE(
                    jsonb_has_exact_keys(body, ARRAY[
                      'target_id','uncertainty_type','representation','drivers','level','explanation'
                    ])
                    AND jsonb_nonempty_text(body, 'level')
                    AND jsonb_nonempty_text(body, 'explanation'),
                    false
                  );
                ELSE RETURN false;
              END CASE;
            WHEN 'RISK' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY[
                  'statement','probability','impact','uncertainty_id','affected_objective_ids'
                ])
                AND jsonb_nonempty_text(body, 'statement')
                AND jsonb_unit_decimal_string(body -> 'probability')
                AND jsonb_nonempty_text(body, 'impact')
                AND jsonb_uuid_text(body -> 'uncertainty_id')
                AND jsonb_all_uuid_texts(body -> 'affected_objective_ids'),
                false
              );
            WHEN 'IMPACT' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY[
                  'alternative_id','objective_id','magnitude','unit','timeframe','source_artifact_id'
                ])
                AND jsonb_uuid_text(body -> 'alternative_id')
                AND jsonb_uuid_text(body -> 'objective_id')
                AND jsonb_decimal_string(body -> 'magnitude')
                AND jsonb_nonempty_text(body, 'unit')
                AND jsonb_nonempty_text(body, 'timeframe')
                AND jsonb_uuid_text(body -> 'source_artifact_id'),
                false
              );
            WHEN 'OBJECTIVE' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY[
                  'name','objective_type','direction','weight','weight_rationale',
                  'time_horizon','conflicts_with_ids'
                ])
                AND jsonb_nonempty_text(body, 'name')
                AND jsonb_nonempty_text(body, 'objective_type')
                AND jsonb_nonempty_text(body, 'direction')
                AND jsonb_unit_decimal_string(body -> 'weight')
                AND jsonb_nonempty_text(body, 'weight_rationale')
                AND jsonb_nonempty_text(body, 'time_horizon')
                AND jsonb_all_uuid_texts(body -> 'conflicts_with_ids'),
                false
              );
            WHEN 'CONSTRAINT' THEN
              expression := body -> 'evaluation_expression';
              RETURN COALESCE(
                jsonb_has_exact_keys(body, ARRAY[
                  'name','statement','constraint_type','category',
                  'evaluation_expression','formal_status'
                ])
                AND jsonb_nonempty_text(body, 'name')
                AND jsonb_nonempty_text(body, 'statement')
                AND body ->> 'constraint_type' IN ('HARD','SOFT','NON_NEGOTIABLE')
                AND jsonb_nonempty_text(body, 'category')
                AND jsonb_has_exact_keys(expression, ARRAY['language','ast'])
                AND jsonb_nonempty_text(expression, 'language')
                AND jsonb_typeof(expression -> 'ast') = 'object'
                AND expression -> 'ast' <> '{}'::jsonb
                AND jsonb_nonempty_text(body, 'formal_status'),
                false
              );
            WHEN 'ALTERNATIVE' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(
                  body, ARRAY['name','summary','components','origin','feasibility_status']
                )
                AND jsonb_nonempty_text(body, 'name')
                AND jsonb_nonempty_text(body, 'summary')
                AND jsonb_all_nonempty_texts(body -> 'components')
                AND jsonb_nonempty_text(body, 'origin')
                AND jsonb_nonempty_text(body, 'feasibility_status'),
                false
              );
            WHEN 'POSITION' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(
                  body, ARRAY['target_id','stance','rationale','evidence_ids','conditions']
                )
                AND jsonb_uuid_text(body -> 'target_id')
                AND body ->> 'stance' IN (
                  'SUPPORT','OPPOSE','CONDITIONALLY_SUPPORT','ABSTAIN','INSUFFICIENT_EVIDENCE'
                )
                AND jsonb_nonempty_text(body, 'rationale')
                AND jsonb_all_uuid_texts(body -> 'evidence_ids')
                AND jsonb_all_nonempty_texts(body -> 'conditions'),
                false
              );
            WHEN 'CRITIQUE' THEN
              RETURN COALESCE(
                jsonb_has_exact_keys(
                  body, ARRAY['target_id','critique_type','severity','argument','resolution']
                )
                AND jsonb_uuid_text(body -> 'target_id')
                AND body ->> 'critique_type' IN (
                  'EVIDENCE_GAP','LOGICAL_FALLACY','HALLUCINATED_SOURCE','MEASUREMENT_ERROR',
                  'MODEL_MISUSE','CONSTRAINT_IGNORED','CONFLICT_OF_INTEREST',
                  'ALTERNATIVE_OMITTED','UNCERTAINTY_UNDERSTATED','CAUSAL_OVERCLAIM'
                )
                AND body ->> 'severity' IN ('LOW','MEDIUM','HIGH','BLOCKING')
                AND jsonb_nonempty_text(body, 'argument')
                AND body ->> 'resolution' IN ('OPEN','RESOLVED','UNRESOLVED','DISPUTED'),
                false
              );
            ELSE RETURN false;
          END CASE;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """
    )


def _create_envelope_validation_function() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_reasoning_artifact_envelope(
          kind_value text,
          version_value integer,
          actor_class text,
          payload_value jsonb,
          provenance_value jsonb,
          source_values jsonb,
          relationship_values jsonb,
          confidence_value jsonb,
          metadata_value jsonb
        ) RETURNS boolean AS $$
        DECLARE
          item jsonb;
        BEGIN
          IF actor_class = 'POLICY'
            OR (kind_value = 'FACT' AND actor_class = 'AGENT') THEN
            RETURN false;
          END IF;

          IF NOT COALESCE(
            jsonb_has_exact_keys(
              provenance_value,
              ARRAY['origin','reference'],
              ARRAY['model_call_id','activity_id']
            )
            AND provenance_value ->> 'origin' IN (
              'HUMAN','LLM','RETRIEVAL','TOOL','SIMULATION','SYMBOLIC',
              'IMPORT','HISTORICAL_SESSION'
            )
            AND jsonb_nonempty_text(provenance_value, 'reference')
            AND (
              NOT provenance_value ? 'model_call_id'
              OR provenance_value -> 'model_call_id' = 'null'::jsonb
              OR jsonb_uuid_text(provenance_value -> 'model_call_id')
            )
            AND (
              NOT provenance_value ? 'activity_id'
              OR provenance_value -> 'activity_id' = 'null'::jsonb
              OR jsonb_uuid_text(provenance_value -> 'activity_id')
            ),
            false
          ) THEN
            RETURN false;
          END IF;
          IF kind_value = 'FACT' AND provenance_value ->> 'origin' = 'LLM' THEN
            RETURN false;
          END IF;
          IF kind_value = 'EVIDENCE'
            AND provenance_value ->> 'origin' = 'HISTORICAL_SESSION' THEN
            RETURN false;
          END IF;

          IF jsonb_typeof(source_values) <> 'array' THEN
            RETURN false;
          END IF;
          IF kind_value IN ('FACT','EVIDENCE') AND jsonb_array_length(source_values) = 0 THEN
            RETURN false;
          END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(source_values) LOOP
            IF NOT COALESCE(
              jsonb_has_exact_keys(
                item,
                ARRAY['reference','locator','content_hash','retrieved_at'],
                ARRAY['source_timestamp']
              )
              AND jsonb_nonempty_text(item, 'reference')
              AND jsonb_typeof(item -> 'locator') = 'object'
              AND item -> 'locator' <> '{}'::jsonb
              AND item ->> 'content_hash' ~ '^sha256:[0-9a-f]{64}$'
              AND item ->> 'retrieved_at' ~
                '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
              AND (
                NOT item ? 'source_timestamp'
                OR item -> 'source_timestamp' = 'null'::jsonb
                OR item ->> 'source_timestamp' ~
                  '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
              ),
              false
            ) THEN
              RETURN false;
            END IF;
          END LOOP;

          IF jsonb_typeof(relationship_values) <> 'array' THEN
            RETURN false;
          END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(relationship_values) LOOP
            IF NOT COALESCE(
              jsonb_has_exact_keys(item, ARRAY['edge_type','target_artifact_id'])
              AND item ->> 'edge_type' IN (
                'SUPPORTS','OPPOSES','CONTRADICTS','DERIVED_FROM','BASED_ON_ASSUMPTION',
                'FORMALIZES','QUANTIFIES','IMPACTS','CONSTRAINS','VIOLATES','SATISFIES',
                'INFEASIBLE_UNKNOWN','ATTACKS','RESPONDS_TO','SUPERSEDES','ADVOCATES'
              )
              AND jsonb_uuid_text(item -> 'target_artifact_id'),
              false
            ) THEN
              RETURN false;
            END IF;
          END LOOP;

          IF confidence_value IS NOT NULL AND confidence_value <> 'null'::jsonb THEN
            IF NOT COALESCE(
              jsonb_has_exact_keys(
                confidence_value, ARRAY['kind','value','meaning','basis_artifact_ids']
              )
              AND jsonb_nonempty_text(confidence_value, 'kind')
              AND jsonb_unit_decimal_string(confidence_value -> 'value')
              AND jsonb_nonempty_text(confidence_value, 'meaning')
              AND jsonb_all_uuid_texts(confidence_value -> 'basis_artifact_ids'),
              false
            ) THEN
              RETURN false;
            END IF;
          END IF;
          IF kind_value = 'POSITION'
            AND (confidence_value IS NULL OR confidence_value = 'null'::jsonb) THEN
            RETURN false;
          END IF;
          IF kind_value = 'FACT'
            AND confidence_value IS NOT NULL AND confidence_value <> 'null'::jsonb THEN
            RETURN false;
          END IF;
          IF kind_value = 'EVIDENCE' AND version_value = 1
            AND payload_value ->> 'verification' <> 'UNVERIFIED' THEN
            RETURN false;
          END IF;
          RETURN jsonb_typeof(metadata_value) = 'object';
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """
    )


def _create_tables() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("budget_tokens", sa.BigInteger(), nullable=False),
        sa.Column("budget_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status = 'DRAFT'", name=op.f("ck_sessions_status_draft")),
        sa.CheckConstraint(
            "length(btrim(problem_statement)) > 0", name=op.f("ck_sessions_problem_not_blank")
        ),
        sa.CheckConstraint(
            "max_rounds BETWEEN 1 AND 50", name=op.f("ck_sessions_max_rounds_range")
        ),
        sa.CheckConstraint("budget_tokens > 0", name=op.f("ck_sessions_budget_tokens_positive")),
        sa.CheckConstraint("budget_usd > 0", name=op.f("ck_sessions_budget_usd_positive")),
        sa.CheckConstraint("round >= 0", name=op.f("ck_sessions_round_nonnegative")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_sessions_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["workspace_members.workspace_id", "workspace_members.user_id"],
            name="fk_sessions_creator_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_sessions_workspace_id"),
    )
    op.create_index(
        "ix_sessions_workspace_status", "sessions", ["workspace_id", "status", "created_at"]
    )
    op.create_table(
        "session_agents",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_def_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "bound_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_agents_session_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_session_agents_agent_workspace",
        ),
        sa.PrimaryKeyConstraint("session_id", "agent_def_id", name="pk_session_agents"),
    )
    op.create_index(
        "ix_session_agents_workspace_agent", "session_agents", ["workspace_id", "agent_def_id"]
    )
    op.create_table(
        "reasoning_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_actor_class", sa.Text(), nullable=False),
        sa.Column("owner_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column(
            "source_references",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "parent_relationships",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence", postgresql.JSONB(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('CLAIM', 'FACT', 'ASSUMPTION', 'INFERENCE', 'PROPOSITION', "
            "'EVIDENCE', 'UNCERTAINTY', 'RISK', 'IMPACT', 'OBJECTIVE', 'CONSTRAINT', "
            "'ALTERNATIVE', 'POSITION', 'CRITIQUE')",
            name=op.f("ck_reasoning_artifacts_kind"),
        ),
        sa.CheckConstraint(
            "schema_version > 0", name=op.f("ck_reasoning_artifacts_schema_version_positive")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_reasoning_artifacts_version_positive")),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUPERSEDED', 'WITHDRAWN')",
            name=op.f("ck_reasoning_artifacts_status"),
        ),
        sa.CheckConstraint(
            "owner_actor_class IN ('HUMAN', 'AGENT', 'SERVICE', 'POLICY')",
            name=op.f("ck_reasoning_artifacts_owner_actor_class"),
        ),
        sa.CheckConstraint("round >= 0", name=op.f("ck_reasoning_artifacts_round_nonnegative")),
        sa.CheckConstraint(
            "content_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_reasoning_artifacts_content_hash_format"),
        ),
        sa.CheckConstraint(
            "((version = 1 AND supersedes_id IS NULL) OR "
            "(version > 1 AND supersedes_id IS NOT NULL))",
            name=op.f("ck_reasoning_artifacts_revision_shape"),
        ),
        sa.CheckConstraint(
            "validate_reasoning_artifact_payload(kind, payload)",
            name=op.f("ck_reasoning_artifacts_payload"),
        ),
        sa.CheckConstraint(
            "validate_reasoning_artifact_envelope(kind, version, owner_actor_class, payload, "
            "provenance, source_references, parent_relationships, confidence, metadata)",
            name=op.f("ck_reasoning_artifacts_envelope"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_reasoning_artifacts_session_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reasoning_artifacts")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_reasoning_artifacts_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "session_id",
            "id",
            name="uq_reasoning_artifacts_workspace_session_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "session_id",
            "logical_id",
            "version",
            name="uq_reasoning_artifacts_logical_version",
        ),
    )
    op.create_foreign_key(
        "fk_reasoning_artifacts_supersedes_workspace_session",
        "reasoning_artifacts",
        "reasoning_artifacts",
        ["workspace_id", "session_id", "supersedes_id"],
        ["workspace_id", "session_id", "id"],
    )
    op.create_index(
        "ix_reasoning_artifacts_session_kind",
        "reasoning_artifacts",
        ["workspace_id", "session_id", "kind", "created_at"],
    )
    for table, expected_kind in (
        ("session_objectives", "OBJECTIVE"),
        ("session_constraints", "CONSTRAINT"),
    ):
        op.create_table(
            table,
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["workspace_id", "session_id"],
                ["sessions.workspace_id", "sessions.id"],
                name=f"fk_{table}_session_workspace",
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id", "session_id", "artifact_id"],
                [
                    "reasoning_artifacts.workspace_id",
                    "reasoning_artifacts.session_id",
                    "reasoning_artifacts.id",
                ],
                name=f"fk_{table}_artifact_workspace_session",
            ),
            sa.PrimaryKeyConstraint("session_id", "artifact_id", name=f"pk_{table}"),
            info={"expected_kind": expected_kind},
        )
        op.create_index(f"ix_{table}_workspace_artifact", table, ["workspace_id", "artifact_id"])


def _create_integrity_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_session_agent_definition() RETURNS trigger AS $$
        DECLARE
          existing_logical_id uuid;
        BEGIN
          SELECT candidate.logical_id INTO existing_logical_id
          FROM session_agents AS binding
          JOIN agent_definitions AS existing
            ON existing.id = binding.agent_def_id
           AND existing.workspace_id = binding.workspace_id
          JOIN agent_definitions AS candidate
            ON candidate.id = NEW.agent_def_id
           AND candidate.workspace_id = NEW.workspace_id
          WHERE binding.session_id = NEW.session_id
            AND binding.agent_def_id <> NEW.agent_def_id
            AND existing.logical_id = candidate.logical_id
          LIMIT 1;
          IF existing_logical_id IS NOT NULL THEN
            RAISE EXCEPTION 'a session cannot bind multiple versions of one logical agent'
              USING ERRCODE = '23514';
          END IF;
          UPDATE agent_definitions
          SET referenced_at = COALESCE(referenced_at, NEW.bound_at)
          WHERE id = NEW.agent_def_id AND workspace_id = NEW.workspace_id;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_session_agent_definition
        AFTER INSERT ON session_agents
        FOR EACH ROW EXECUTE FUNCTION enforce_session_agent_definition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_session_binding_kind() RETURNS trigger AS $$
        DECLARE
          actual_kind text;
          expected_kind text;
        BEGIN
          expected_kind := CASE TG_TABLE_NAME
            WHEN 'session_objectives' THEN 'OBJECTIVE'
            WHEN 'session_constraints' THEN 'CONSTRAINT'
          END;
          SELECT kind INTO actual_kind
          FROM reasoning_artifacts
          WHERE workspace_id = NEW.workspace_id
            AND session_id = NEW.session_id
            AND id = NEW.artifact_id;
          IF actual_kind IS DISTINCT FROM expected_kind THEN
            RAISE EXCEPTION '% requires artifact kind %, got %',
              TG_TABLE_NAME, expected_kind, actual_kind USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("session_objectives", "session_constraints"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_kind "
            f"AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION enforce_session_binding_kind()"
        )

    op.execute(
        """
        CREATE FUNCTION enforce_artifact_revision_chain() RETURNS trigger AS $$
        DECLARE
          predecessor reasoning_artifacts%ROWTYPE;
        BEGIN
          IF NEW.version = 1 THEN
            RETURN NEW;
          END IF;
          SELECT * INTO predecessor
          FROM reasoning_artifacts
          WHERE workspace_id = NEW.workspace_id
            AND session_id = NEW.session_id
            AND id = NEW.supersedes_id;
          IF predecessor.id IS NULL
            OR predecessor.logical_id <> NEW.logical_id
            OR predecessor.kind <> NEW.kind
            OR predecessor.version <> NEW.version - 1 THEN
            RAISE EXCEPTION
              'artifact revision must supersede the previous same-kind logical version'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_reasoning_artifact_revision
        AFTER INSERT OR UPDATE ON reasoning_artifacts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_artifact_revision_chain();
        """
    )

    op.execute(
        """
        CREATE FUNCTION artifact_reference_exists(
          workspace_value uuid,
          session_value uuid,
          artifact_value jsonb
        ) RETURNS boolean AS $$
          SELECT jsonb_uuid_text(artifact_value) AND EXISTS (
            SELECT 1 FROM reasoning_artifacts
            WHERE workspace_id = workspace_value
              AND session_id = session_value
              AND id = (artifact_value #>> '{}')::uuid
          );
        $$ LANGUAGE sql STABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_artifact_references() RETURNS trigger AS $$
        DECLARE
          reference_value jsonb;
        BEGIN
          FOR reference_value IN
            SELECT value FROM jsonb_array_elements(NEW.parent_relationships)
          LOOP
            IF NOT artifact_reference_exists(
              NEW.workspace_id, NEW.session_id, reference_value -> 'target_artifact_id'
            ) THEN
              RAISE EXCEPTION 'parent relationship target must exist in the artifact session'
                USING ERRCODE = '23503';
            END IF;
          END LOOP;
          IF NEW.confidence IS NOT NULL THEN
            FOR reference_value IN
              SELECT value FROM jsonb_array_elements(NEW.confidence -> 'basis_artifact_ids')
            LOOP
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, reference_value
              ) THEN
                RAISE EXCEPTION 'confidence basis must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
            END LOOP;
          END IF;

          CASE NEW.kind
            WHEN 'CLAIM' THEN
              FOR reference_value IN
                SELECT value FROM jsonb_array_elements(
                  (NEW.payload -> 'supporting_evidence_ids') ||
                  (NEW.payload -> 'opposing_evidence_ids')
                )
              LOOP
                IF NOT artifact_reference_exists(
                  NEW.workspace_id, NEW.session_id, reference_value
                ) THEN
                  RAISE EXCEPTION 'claim evidence must exist in the artifact session'
                    USING ERRCODE = '23503';
                END IF;
              END LOOP;
            WHEN 'INFERENCE' THEN
              FOR reference_value IN
                SELECT value FROM jsonb_array_elements(NEW.payload -> 'premise_ids')
              LOOP
                IF NOT artifact_reference_exists(
                  NEW.workspace_id, NEW.session_id, reference_value
                ) THEN
                  RAISE EXCEPTION 'inference premise must exist in the artifact session'
                    USING ERRCODE = '23503';
                END IF;
              END LOOP;
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'conclusion_id'
              ) THEN
                RAISE EXCEPTION 'inference conclusion must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
            WHEN 'EVIDENCE' THEN
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'claim_id'
              ) THEN
                RAISE EXCEPTION 'evidence claim must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
            WHEN 'UNCERTAINTY' THEN
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'target_id'
              ) THEN
                RAISE EXCEPTION 'uncertainty target must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
            WHEN 'RISK' THEN
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'uncertainty_id'
              ) THEN
                RAISE EXCEPTION 'risk uncertainty must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
              FOR reference_value IN
                SELECT value FROM jsonb_array_elements(NEW.payload -> 'affected_objective_ids')
              LOOP
                IF NOT artifact_reference_exists(
                  NEW.workspace_id, NEW.session_id, reference_value
                ) THEN
                  RAISE EXCEPTION 'risk objective must exist in the artifact session'
                    USING ERRCODE = '23503';
                END IF;
              END LOOP;
            WHEN 'IMPACT' THEN
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'alternative_id'
              ) OR NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'objective_id'
              ) OR NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'source_artifact_id'
              ) THEN
                RAISE EXCEPTION 'impact references must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
            WHEN 'OBJECTIVE' THEN
              FOR reference_value IN
                SELECT value FROM jsonb_array_elements(NEW.payload -> 'conflicts_with_ids')
              LOOP
                IF NOT artifact_reference_exists(
                  NEW.workspace_id, NEW.session_id, reference_value
                ) THEN
                  RAISE EXCEPTION 'objective conflict must exist in the artifact session'
                    USING ERRCODE = '23503';
                END IF;
              END LOOP;
            WHEN 'POSITION' THEN
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'target_id'
              ) THEN
                RAISE EXCEPTION 'position target must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
              FOR reference_value IN
                SELECT value FROM jsonb_array_elements(NEW.payload -> 'evidence_ids')
              LOOP
                IF NOT artifact_reference_exists(
                  NEW.workspace_id, NEW.session_id, reference_value
                ) THEN
                  RAISE EXCEPTION 'position evidence must exist in the artifact session'
                    USING ERRCODE = '23503';
                END IF;
              END LOOP;
            WHEN 'CRITIQUE' THEN
              IF NOT artifact_reference_exists(
                NEW.workspace_id, NEW.session_id, NEW.payload -> 'target_id'
              ) THEN
                RAISE EXCEPTION 'critique target must exist in the artifact session'
                  USING ERRCODE = '23503';
              END IF;
            ELSE NULL;
          END CASE;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_reasoning_artifact_references
        AFTER INSERT OR UPDATE ON reasoning_artifacts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_artifact_references();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_reasoning_artifact_immutability() RETURNS trigger AS $$
        BEGIN
          IF NEW.id IS DISTINCT FROM OLD.id
            OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
            OR NEW.session_id IS DISTINCT FROM OLD.session_id
            OR NEW.logical_id IS DISTINCT FROM OLD.logical_id
            OR NEW.kind IS DISTINCT FROM OLD.kind
            OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
            OR NEW.version IS DISTINCT FROM OLD.version
            OR NEW.supersedes_id IS DISTINCT FROM OLD.supersedes_id
            OR NEW.owner_actor_class IS DISTINCT FROM OLD.owner_actor_class
            OR NEW.owner_actor_id IS DISTINCT FROM OLD.owner_actor_id
            OR NEW.round IS DISTINCT FROM OLD.round
            OR NEW.payload IS DISTINCT FROM OLD.payload
            OR NEW.provenance IS DISTINCT FROM OLD.provenance
            OR NEW.source_references IS DISTINCT FROM OLD.source_references
            OR NEW.parent_relationships IS DISTINCT FROM OLD.parent_relationships
            OR NEW.confidence IS DISTINCT FROM OLD.confidence
            OR NEW.metadata IS DISTINCT FROM OLD.metadata
            OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
            OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'reasoning artifact content is immutable' USING ERRCODE = '27000';
          END IF;
          IF NOT (
            NEW.status = OLD.status
            OR (OLD.status = 'ACTIVE' AND NEW.status IN ('SUPERSEDED','WITHDRAWN'))
          ) THEN
            RAISE EXCEPTION 'invalid reasoning artifact lifecycle transition'
              USING ERRCODE = '23514';
          END IF;
          IF NEW.updated_at < OLD.updated_at THEN
            RAISE EXCEPTION 'artifact updated_at cannot move backwards' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reasoning_artifact_immutable
        BEFORE UPDATE ON reasoning_artifacts
        FOR EACH ROW EXECUTE FUNCTION enforce_reasoning_artifact_immutability();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_reasoning_artifact_delete() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'reasoning artifacts cannot be deleted' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reasoning_artifact_no_delete
        BEFORE DELETE ON reasoning_artifacts
        FOR EACH ROW EXECUTE FUNCTION reject_reasoning_artifact_delete();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_complete_session_binding() RETURNS trigger AS $$
        DECLARE
          target_workspace_id uuid;
          target_session_id uuid;
        BEGIN
          IF TG_TABLE_NAME = 'sessions' THEN
            target_workspace_id := NEW.workspace_id;
            target_session_id := NEW.id;
          ELSE
            target_workspace_id := OLD.workspace_id;
            target_session_id := OLD.session_id;
          END IF;

          IF EXISTS (
            SELECT 1 FROM sessions
            WHERE workspace_id = target_workspace_id AND id = target_session_id
          ) AND (
            NOT EXISTS (
              SELECT 1 FROM session_agents
              WHERE workspace_id = target_workspace_id AND session_id = target_session_id
            )
            OR NOT EXISTS (
              SELECT 1 FROM session_objectives
              WHERE workspace_id = target_workspace_id AND session_id = target_session_id
            )
          ) THEN
            RAISE EXCEPTION 'a session requires at least one agent and objective'
              USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_session_complete_binding
        AFTER INSERT OR UPDATE ON sessions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_complete_session_binding();
        """
    )
    for table in ("session_agents", "session_objectives"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_complete_binding "
            f"AFTER DELETE OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION enforce_complete_session_binding()"
        )


def upgrade() -> None:
    _create_json_validation_functions()
    _create_payload_validation_function()
    _create_envelope_validation_function()
    _create_tables()
    _create_integrity_triggers()
    for table in _TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_session_objectives_complete_binding ON session_objectives"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_session_agents_complete_binding ON session_agents")
    op.execute("DROP TRIGGER IF EXISTS trg_session_complete_binding ON sessions")
    op.execute("DROP FUNCTION IF EXISTS enforce_complete_session_binding()")
    op.execute("DROP TRIGGER IF EXISTS trg_reasoning_artifact_no_delete ON reasoning_artifacts")
    op.execute("DROP FUNCTION IF EXISTS reject_reasoning_artifact_delete()")
    op.execute("DROP TRIGGER IF EXISTS trg_reasoning_artifact_immutable ON reasoning_artifacts")
    op.execute("DROP FUNCTION IF EXISTS enforce_reasoning_artifact_immutability()")
    op.execute("DROP TRIGGER IF EXISTS trg_reasoning_artifact_references ON reasoning_artifacts")
    op.execute("DROP FUNCTION IF EXISTS enforce_artifact_references()")
    op.execute("DROP FUNCTION IF EXISTS artifact_reference_exists(uuid, uuid, jsonb)")
    op.execute("DROP TRIGGER IF EXISTS trg_reasoning_artifact_revision ON reasoning_artifacts")
    op.execute("DROP FUNCTION IF EXISTS enforce_artifact_revision_chain()")
    op.execute("DROP TRIGGER IF EXISTS trg_session_constraints_kind ON session_constraints")
    op.execute("DROP TRIGGER IF EXISTS trg_session_objectives_kind ON session_objectives")
    op.execute("DROP FUNCTION IF EXISTS enforce_session_binding_kind()")
    op.execute("DROP TRIGGER IF EXISTS trg_session_agent_definition ON session_agents")
    op.execute("DROP FUNCTION IF EXISTS enforce_session_agent_definition()")
    op.drop_table("session_constraints")
    op.drop_table("session_objectives")
    op.drop_table("reasoning_artifacts")
    op.drop_table("session_agents")
    op.drop_table("sessions")
    op.execute(
        "DROP FUNCTION IF EXISTS validate_reasoning_artifact_envelope("
        "text, integer, text, jsonb, jsonb, jsonb, jsonb, jsonb, jsonb)"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_reasoning_artifact_payload(text, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS jsonb_unit_decimal_string(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS jsonb_decimal_string(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS jsonb_all_nonempty_texts(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS jsonb_all_uuid_texts(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS jsonb_uuid_text(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS jsonb_nonempty_text(jsonb, text)")
    op.execute("DROP FUNCTION IF EXISTS jsonb_has_exact_keys(jsonb, text[], text[])")
