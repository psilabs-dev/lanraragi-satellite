import numpy as np

from manycbz.service.metadata import create_tag_generators, get_tag_assignments

# step function
def pmf_1(t: float) -> float:
    return 0 if t < 0.5 else 1

# exp decay function
def pmf_2(t: float) -> float:
    return 2 ** (-t * 10_000)

def test_create_tag_generators():
    tag_generators = create_tag_generators(4, pmf_1)
    assert np.isclose(tag_generators[0].assign_probability, 0)
    assert np.isclose(tag_generators[1].assign_probability, 0)
    assert np.isclose(tag_generators[2].assign_probability, 1)
    assert np.isclose(tag_generators[3].assign_probability, 1)

def test_get_tag_assignments():
    generator = np.random.default_rng(42)
    tag_generators = create_tag_generators(10_000, pmf_2)
    tag_assignments = get_tag_assignments(tag_generators, generator=generator)
    assert tag_assignments, ['tag-0', 'tag-2', 'tag-5']
