from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from recosearch.semantic_layers.metrics.types import Relation

_CARDINALITY_INVERSE = {
    "one_to_one": "one_to_one",
    "one_to_many": "many_to_one",
    "many_to_one": "one_to_many",
    "many_to_many": "many_to_many",
}


@dataclass(frozen=True, slots=True)
class RelationStep:
    relation_id: str
    from_entity_id: str
    to_entity_id: str
    join_key: str
    cardinality: str


def invert_cardinality(cardinality: str) -> str:
    try:
        return _CARDINALITY_INVERSE[cardinality]
    except KeyError as exc:
        raise ValueError(f"unknown cardinality {cardinality}") from exc


def _step_for_direction(relation: Relation, *, reversed_dir: bool) -> RelationStep:
    if reversed_dir:
        return RelationStep(
            relation_id=relation.relation_id,
            from_entity_id=relation.to_entity_id,
            to_entity_id=relation.from_entity_id,
            join_key=relation.join_key,
            cardinality=invert_cardinality(relation.cardinality),
        )
    return RelationStep(
        relation_id=relation.relation_id,
        from_entity_id=relation.from_entity_id,
        to_entity_id=relation.to_entity_id,
        join_key=relation.join_key,
        cardinality=relation.cardinality,
    )


def _path_key(path: list[RelationStep]) -> tuple[str, ...]:
    return tuple(step.relation_id for step in path)


def plan_relation_path(
    relations: Mapping[str, Relation],
    from_entity_id: str,
    to_entity_id: str,
) -> list[RelationStep]:
    if from_entity_id == to_entity_id:
        return []

    adjacency: dict[str, list[tuple[str, Relation, bool]]] = {}
    for relation in relations.values():
        adjacency.setdefault(relation.from_entity_id, []).append((relation.to_entity_id, relation, False))
        adjacency.setdefault(relation.to_entity_id, []).append((relation.from_entity_id, relation, True))

    current_layer: dict[str, list[list[RelationStep]]] = {from_entity_id: [[]]}
    while current_layer:
        target_paths: list[list[RelationStep]] = []
        next_layer: dict[str, list[list[RelationStep]]] = {}

        for node in sorted(current_layer):
            for path in current_layer[node]:
                visited_entities = {from_entity_id, *{step.to_entity_id for step in path}}
                for neighbor, relation, reversed_dir in sorted(
                    adjacency.get(node, []),
                    key=lambda item: (item[0], item[1].relation_id),
                ):
                    if neighbor in visited_entities:
                        continue
                    step = _step_for_direction(relation, reversed_dir=reversed_dir)
                    new_path = path + [step]
                    if neighbor == to_entity_id:
                        target_paths.append(new_path)
                    else:
                        next_layer.setdefault(neighbor, []).append(new_path)

        if target_paths:
            return min(target_paths, key=_path_key)

        current_layer = next_layer

    raise ValueError(f"no relation path from {from_entity_id} to {to_entity_id}")


def path_has_additive_fanout(path: list[RelationStep], aggregation: str) -> RelationStep | None:
    if aggregation.lower() != "sum":
        return None
    for step in path:
        if step.cardinality == "one_to_many":
            return step
    return None
