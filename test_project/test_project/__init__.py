from pyramid.config import Configurator
from sqlalchemy import engine_from_config
from pyramid.renderers import JSON
from . import views

# The jsonapi module.
import pyramid_jsonapi

# Import models as a module: needed for create_jsonapi...
from . import models

from pyramid.httpexceptions import (
    HTTPForbidden
)

# Used to test that adding JSON adapters works.
import datetime
def datetime_adapter(obj, request):
    return obj.isoformat()


def person_callback_add_information(view, ret):
    ret['attributes']['name_copy'] = ret['attributes']['name']
    ret['attributes']['age'] = 42
    return ret


def secret_squirrel_callback(view, ret):
    if ret['attributes']['name'] == 'secret_squirrel':
        if view.request.matchdict.get('id', None):
            raise HTTPForbidden('You cannot see Secret Squirrel.')
        else:
            ret = {
                'type': ret['type'],
                'id': ret['id'],
                'meta': {
                    'errors': [
                        {
                            'code': 403,
                            'title': 'Forbidden',
                            'detail': 'No permission to view this object.'
                        }
                    ]
                }
            }
    return ret


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    # The usual stuff from the pyramid alchemy scaffold.
    engine = engine_from_config(settings, 'sqlalchemy.')
    models.DBSession.configure(bind=engine)
    models.Base.metadata.bind = engine
    config = Configurator(settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    config.add_route('echo', '/echo/{type}')
    config.scan(views)

    # Set up the renderer.
    renderer = JSON()
    renderer.add_adapter(datetime.date, datetime_adapter)
    config.add_renderer('json', renderer)

    # Lines specific to pyramid_jsonapi.
    # Create the routes and views automagically.
    pyramid_jsonapi.create_jsonapi_using_magic_and_pixie_dust(
        config, models, lambda view: models.DBSession
    )
    pyramid_jsonapi.view_classes[
        models.Person
    ].serialise_dict_callbacks.extend(
        (person_callback_add_information, secret_squirrel_callback)
    )

    # Back to the usual pyramid stuff.
    return config.make_wsgi_app()
