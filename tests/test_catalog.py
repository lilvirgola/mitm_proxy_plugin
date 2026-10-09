from mitm_proxy_plugin.core.rng import SeededRNG
from mitm_proxy_plugin.mutations.catalog import MutantCatalog

def make_minimal_spec():
    return {
        "paths": {
            "/api/items": {
                "get": {
                    "operationId": "getItems",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "name": {"type": "string"},
                                        },
                                        "required": ["id"],
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }


def test_catalog_generates_mutants():
    spec = make_minimal_spec()
    rng = SeededRNG()
    rng.set_seed(42)

    catalog = MutantCatalog(spec, rng)
    catalog.generate()

    assert catalog.total_mutants() > 0
    assert "getItems" in catalog.catalog


def test_catalog_deterministic():
    spec = make_minimal_spec()

    rng1 = SeededRNG()
    rng1.set_seed(42)
    catalog1 = MutantCatalog(spec, rng1)
    catalog1.generate()

    rng2 = SeededRNG()
    rng2.set_seed(42)
    catalog2 = MutantCatalog(spec, rng2)
    catalog2.generate()

    assert catalog1.total_mutants() == catalog2.total_mutants()


def test_disabled_operators():
    spec = make_minimal_spec()
    rng = SeededRNG()
    rng.set_seed(42)

    catalog = MutantCatalog(spec, rng, disabled_operators={"MalformedJSON"})
    catalog.generate()

    for op_id, mutants in catalog.catalog.items():
        for mutant in mutants:
            assert mutant["operator"] != "MalformedJSON"