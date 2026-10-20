def test_packages_import() -> None:
    import fleet_sim
    from fleet_sim import coordination, data, experiments, fleet, models, optimise, viz

    assert fleet_sim.__name__ == "fleet_sim"
    assert data.__name__ == "fleet_sim.data"
    assert models.__name__ == "fleet_sim.models"
    assert optimise.__name__ == "fleet_sim.optimise"
    assert fleet.__name__ == "fleet_sim.fleet"
    assert coordination.__name__ == "fleet_sim.coordination"
    assert experiments.__name__ == "fleet_sim.experiments"
    assert viz.__name__ == "fleet_sim.viz"
