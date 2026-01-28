# Routes package - registers all blueprints with the Flask app

def register_blueprints(app):
    """Register all route blueprints with the Flask app."""
    from .pager import pager_bp
    from .sensor import sensor_bp
    from .rtlamr import rtlamr_bp
    from .wifi import wifi_bp
    from .wifi_v2 import wifi_v2_bp
    from .bluetooth import bluetooth_bp
    from .bluetooth_v2 import bluetooth_v2_bp
    from .adsb import adsb_bp
    from .ais import ais_bp
    from .dsc import dsc_bp
    from .acars import acars_bp
    from .aprs import aprs_bp
    from .satellite import satellite_bp
    from .gps import gps_bp
    from .settings import settings_bp
    from .correlation import correlation_bp
    from .listening_post import listening_post_bp
    from .tscm import tscm_bp, init_tscm_state
    from .mqtt import mqtt_bp
    from .spy_stations import spy_stations_bp
    from .controller import controller_bp

    app.register_blueprint(pager_bp)
    app.register_blueprint(sensor_bp)
    app.register_blueprint(rtlamr_bp)
    app.register_blueprint(wifi_bp)
    app.register_blueprint(wifi_v2_bp)  # New unified WiFi API
    app.register_blueprint(bluetooth_bp)
    app.register_blueprint(bluetooth_v2_bp)  # New unified Bluetooth API
    app.register_blueprint(adsb_bp)
    app.register_blueprint(ais_bp)
    app.register_blueprint(dsc_bp)  # VHF DSC maritime distress
    app.register_blueprint(acars_bp)
    app.register_blueprint(aprs_bp)
    app.register_blueprint(satellite_bp)
    app.register_blueprint(gps_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(correlation_bp)
    app.register_blueprint(listening_post_bp)
    app.register_blueprint(tscm_bp)
    app.register_blueprint(mqtt_bp)
    app.register_blueprint(spy_stations_bp)
    app.register_blueprint(controller_bp)  # Remote agent controller

    # Initialize TSCM state with queue and lock from app
    import app as app_module
    if hasattr(app_module, 'tscm_queue') and hasattr(app_module, 'tscm_lock'):
        init_tscm_state(app_module.tscm_queue, app_module.tscm_lock)
