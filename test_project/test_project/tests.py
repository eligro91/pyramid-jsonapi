import unittest
import transaction
import testing.postgresql
import webtest
import datetime
from pyramid.paster import get_app
from sqlalchemy import create_engine
from sqlalchemy.exc import SAWarning
import test_project
import inspect
import os
import urllib
import warnings

from test_project.models import (
    DBSession,
    Base
)

from test_project import test_data

cur_dir = os.path.dirname(
    os.path.abspath(
        inspect.getfile(inspect.currentframe())
    )
)
parent_dir = os.path.dirname(cur_dir)


def setUpModule():
    '''Create a test DB and import data.'''
    # Create a new database somewhere in /tmp
    global postgresql
    global engine
    postgresql = testing.postgresql.Postgresql(port=7654)
    engine = create_engine(postgresql.url())
    DBSession.configure(bind=engine)


def tearDownModule():
    '''Throw away test DB.'''
    global postgresql
    DBSession.close()
    postgresql.stop()


class DBTestBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        '''Create a test app.'''
        with warnings.catch_warnings():
            # Suppress SAWarning: about Property _jsonapi_id being replaced by
            # Propery _jsonapi_id every time a new app is instantiated.
            warnings.simplefilter(
                "ignore",
                category=SAWarning
            )
            cls.app = get_app('{}/testing.ini'.format(parent_dir))
        cls.test_app = webtest.TestApp(cls.app)

    def setUp(self):
        Base.metadata.create_all(engine)
        # Add some basic test data.
        test_data.add_to_db()
        transaction.begin()

    def tearDown(self):
        transaction.abort()
        Base.metadata.drop_all(engine)


class TestSpec(DBTestBase):
    '''Test compliance against jsonapi spec.

    http://jsonapi.org/format/
    '''

    ###############################################
    # GET tests.
    ###############################################

    def test_spec_server_content_type(self):
        '''Response should have correct content type.

        Servers MUST send all JSON API data in response documents with the
        header Content-Type: application/vnd.api+json without any media type
        parameters.
        '''
        # Fetch a representative page

        r = self.test_app.get('/people')
        self.assertEqual(r.content_type, 'application/vnd.api+json')

    def test_spec_incorrect_client_content_type(self):
        '''Server should return error if we send media type parameters.

        Servers MUST respond with a 415 Unsupported Media Type status code if a
        request specifies the header Content-Type: application/vnd.api+json with
        any media type parameters.
        '''
        r = self.test_app.get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )

    def test_spec_accept_not_acceptable(self):
        '''Server should respond with 406 if all jsonapi media types have parameters.

        Servers MUST respond with a 406 Not Acceptable status code if a
        request’s Accept header contains the JSON API media type and all
        instances of that media type are modified with media type parameters.
        '''
        # Should work with correct accepts header.
        r = self.test_app.get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json' },
        )
        # 406 with one incorrect type.
        r = self.test_app.get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json; param=val' },
            status=406,
        )
        # 406 with more than one type but none without params.
        r = self.test_app.get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json; param=val,' +
                'application/vnd.api+json; param2=val2' },
            status=406,
        )

    def test_spec_toplevel_must(self):
        '''Server response must have one of data, errors or meta.

        A JSON object MUST be at the root of every JSON API request and response
        containing data.

        A document MUST contain at least one of the following top-level members:

            * data: the document’s “primary data”
            * errors: an array of error objects
            * meta: a meta object that contains non-standard meta-information.
        '''
        # Should be object with data member.
        r = self.test_app.get('/people')
        self.assertIn('data', r.json)
        # Should also have a meta member.
        self.assertIn('meta', r.json)

        # Should be object with an array of errors.
        r = self.test_app.get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )
        self.assertIn('errors', r.json)
        self.assertIsInstance(r.json['errors'], list)

    def test_spec_get_primary_data_empty(self):
        '''Should return an empty list of results.

        Primary data MUST be either:

            * ...or an empty array ([])

        A logical collection of resources MUST be represented as an array, even
        if it... is empty.
        '''
        r = self.test_app.get('/people?filter[name:eq]=doesnotexist')
        self.assertEqual(len(r.json['data']), 0)

    def test_spec_get_primary_data_array(self):
        '''Should return an array of resource objects.

        Primary data MUST be either:

            * an array of resource objects, an array of resource identifier
            objects, or an empty array ([]), for requests that target resource
            collections
        '''
        # Data should be an array of person resource objects or identifiers.
        r = self.test_app.get('/people')
        self.assertIn('data', r.json)
        self.assertIsInstance(r.json['data'], list)
        item = r.json['data'][0]


    def test_spec_get_primary_data_array_of_one(self):
        '''Should return an array of one resource object.

        A logical collection of resources MUST be represented as an array, even
        if it only contains one item...
        '''
        r = self.test_app.get('/people?page[limit]=1')
        self.assertIn('data', r.json)
        self.assertIsInstance(r.json['data'], list)
        self.assertEqual(len(r.json['data']), 1)

    def test_spec_get_primary_data_single(self):
        '''Should return a single resource object.

        Primary data MUST be either:

            * a single resource object, a single resource identifier object, or
            null, for requests that target single resources
        '''
        # Find the id of alice.
        r = self.test_app.get('/people?filter[name:eq]=alice')
        item = r.json['data'][0]
        self.assertEqual(item['attributes']['name'], 'alice')
        alice_id = item['id']
        # Now get alice object.
        r = self.test_app.get('/people/' + alice_id)
        alice = r.json['data']
        self.assertEqual(alice['attributes']['name'], 'alice')

    def test_spec_resource_object_must(self):
        '''Resource object should have at least id and type.

        A resource object MUST contain at least the following top-level members:
            * id
            * type

        The values of the id and type members MUST be strings.
        '''
        r = self.test_app.get('/people?page[limit]=1')
        item = r.json['data'][0]
        # item must have at least a type and id.
        self.assertEqual(item['type'], 'people')
        self.assertIn('id', item)
        self.assertIsInstance(item['type'], str)
        self.assertIsInstance(item['id'], str)

    def test_spec_resource_object_should(self):
        '''Fetched resource should have attributes, relationships, links, meta.

        a resource object MAY contain any of these top-level members:

            * attributes: an attributes object representing some of the
              resource’s data.

            * relationships: a relationships object describing relationships
              between the resource and other JSON API resources.

            * links: a links object containing links related to the resource.

            * meta: a meta object containing non-standard meta-information about
              a resource that can not be represented as an attribute or
              relationship.
        '''
        r = self.test_app.get('/people?page[limit]=1')
        item = r.json['data'][0]
        self.assertIn('attributes', item)
        #self.assertIn('relationships', item)
        self.assertIn('links', item)
        #self.assertIn('meta', item)

    def test_spec_type_id_identify_resource(self):
        '''Using type and id should fetch a single resource.

        Within a given API, each resource object’s type and id pair MUST
        identify a single, unique resource.
        '''
        # Find the id of alice.
        r = self.test_app.get('/people?filter[name:eq]=alice')
        item = r.json['data'][0]
        self.assertEqual(item['attributes']['name'], 'alice')
        alice_id = item['id']

        # Search for alice by id. We should get one result whose name is alice.
        r = self.test_app.get('/people?filter[id:eq]={}'.format(alice_id))
        self.assertEqual(len(r.json['data']), 1)
        item = r.json['data'][0]
        self.assertEqual(item['id'], alice_id)
        self.assertEqual(item['attributes']['name'], 'alice')

    def test_spec_attributes(self):
        '''attributes key should be an object.

        The value of the attributes key MUST be an object (an “attributes
        object”). Members of the attributes object (“attributes”) represent
        information about the resource object in which it’s defined.
        '''
        # Fetch a single post.
        r = self.test_app.get('/posts?page[limit]=1')
        item = r.json['data'][0]
        # Check attributes.
        self.assertIn('attributes', item)
        atts = item['attributes']
        self.assertIn('title', atts)
        self.assertIn('content', atts)
        self.assertIn('published_at', atts)

    def test_spec_no_foreign_keys(self):
        '''No forreign keys in attributes.

        Although has-one foreign keys (e.g. author_id) are often stored
        internally alongside other information to be represented in a resource
        object, these keys SHOULD NOT appear as attributes.
        '''
        # posts have author_id and blog_id as has-one forreign keys. Check that
        # they don't make it into the JSON representation (they should be in
        # relationships instead).

        # Fetch a single post.
        r = self.test_app.get('/posts?page[limit]=1')
        item = r.json['data'][0]
        # Check for forreign keys.
        self.assertNotIn('author_id', item['attributes'])
        self.assertNotIn('blog_id', item['attributes'])

    def test_spec_relationships_object(self):
        '''Relationships key should be object.

        The value of the relationships key MUST be an object (a “relationships
        object”). Members of the relationships object (“relationships”)
        represent references from the resource object in which it’s defined to
        other resource objects.
        '''
        # Fetch a single blog (has to-one and to-many realtionships)
        r = self.test_app.get('/blogs?page[limit]=1')
        item = r.json['data'][0]
        # Should have relationships key
        self.assertIn('relationships', item)
        rels = item['relationships']

        # owner: to-one
        self.assertIn('owner', rels)
        owner = rels['owner']
        self.assertIn('links', owner)
        self.assertIn('data', owner)
        self.assertIsInstance(owner['data'], dict)
        self.assertIn('type', owner['data'])
        self.assertIn('id', owner['data'])

        # posts: to-many
        self.assertIn('posts', rels)
        posts = rels['posts']
        self.assertIn('links', posts)
        self.assertIn('data', posts)
        self.assertIsInstance(posts['data'], list)
        self.assertIn('type', posts['data'][0])
        self.assertIn('id', posts['data'][0])

    def test_spec_relationships_links(self):
        '''Relationships links object should have 'self' and 'related' links.
        '''
        # Fetch a single blog (has to-one and to-many relationships)
        r = self.test_app.get('/blogs?page[limit]=1')
        item = r.json['data'][0]
        # Should have relationships key
        links = item['relationships']['owner']['links']
        self.assertIn('self', links)
        self.assertTrue(
            links['self'].endswith(
                '/blogs/{}/relationships/owner'.format(item['id'])
            )
        )
        self.assertIn('related', links)
        self.assertTrue(
            links['related'].endswith(
                '/blogs/{}/owner'.format(item['id'])
            )
        )

    def test_spec_related_get(self):
        ''''related' link should fetch related resource(s).

        If present, a related resource link MUST reference a valid URL, even if
        the relationship isn’t currently associated with any target resources.
        '''
        # Fetch a single blog (has to-one and to-many relationships)
        r = self.test_app.get('/blogs/1')
        item = r.json['data']
        owner_url = item['relationships']['owner']['links']['related']
        posts_url = item['relationships']['posts']['links']['related']

        owner_data = self.test_app.get(owner_url).json['data']
        # owner should be a single object.
        self.assertIsInstance(owner_data, dict)
        # owner should be of type 'people'
        self.assertEqual(owner_data['type'], 'people')

        posts_data = self.test_app.get(posts_url).json['data']
        # posts should be a collection.
        self.assertIsInstance(posts_data, list)
        # each post should be of type 'posts'
        for post in posts_data:
            self.assertEqual(post['type'], 'posts')

    def test_spec_resource_linkage(self):
        '''Appropriate related resource identifiers in relationship.

        Resource linkage in a compound document allows a client to link together
        all of the included resource objects without having to GET any URLs via
        links.

        Resource linkage MUST be represented as one of the following:

            * null for empty to-one relationships.
            * an empty array ([]) for empty to-many relationships.
            * a single resource identifier object for non-empty to-one
             relationships.
            * an array of resource identifier objects for non-empty to-many
             relationships.
        '''
        # An anonymous comment.
        # 'null for empty to-one relationships.'
        comment = self.test_app.get('/comments/5').json['data']
        self.assertIsNone(comment['relationships']['author']['data'])

        # A comment with an author.
        # 'a single resource identifier object for non-empty to-one
        # relationships.'
        comment = self.test_app.get('/comments/1').json['data']
        author = comment['relationships']['author']['data']
        self.assertEqual(author['type'], 'people')

        # A post with no comments.
        # 'an empty array ([]) for empty to-many relationships.'
        post = self.test_app.get('/posts/1').json['data']
        comments = post['relationships']['comments']['data']
        self.assertEqual(len(comments), 0)

        # A post with comments.
        # 'an array of resource identifier objects for non-empty to-many
        # relationships.'
        post = self.test_app.get('/posts/4').json['data']
        comments = post['relationships']['comments']['data']
        self.assertGreater(len(comments), 0)
        self.assertEqual(comments[0]['type'], 'comments')

    def test_spec_links_self(self):
        ''''self' link should fetch same object.

        The optional links member within each resource object contains links
        related to the resource.

        If present, this links object MAY contain a self link that identifies
        the resource represented by the resource object.

        A server MUST respond to a GET request to the specified URL with a
        response that includes the resource as the primary data.
        '''
        person = self.test_app.get('/people/1').json['data']
        # Make sure we got the expected person.
        self.assertEqual(person['type'], 'people')
        self.assertEqual(person['id'], '1')
        # Now fetch the self link.
        person_again = self.test_app.get(person['links']['self']).json['data']
        # Make sure we got the same person.
        self.assertEqual(person_again['type'], 'people')
        self.assertEqual(person_again['id'], '1')

    def test_spec_included_array(self):
        '''Included resources should be in an array under 'included' member.

        In a compound document, all included resources MUST be represented as an
        array of resource objects in a top-level included member.
        '''
        person = self.test_app.get('/people/1?include=blogs').json
        self.assertIsInstance(person['included'], list)
        # Each item in the list should be a resource object: we'll look for
        # type, id and attributes.
        for blog in person['included']:
            self.assertIn('id', blog)
            self.assertEqual(blog['type'], 'blogs')
            self.assertIn('attributes', blog)

    def test_spec_bad_include(self):
        '''Should 400 error on attempt to fetch non existent relationship path.

        If a server is unable to identify a relationship path or does not
        support inclusion of resources from a path, it MUST respond with 400 Bad
        Request.
        '''
        # Try to include a relationship that doesn't exist.
        r = self.test_app.get('/people/1?include=frogs', status=400)

    def test_spec_nested_include(self):
        '''Should return includes for nested resources.

        In order to request resources related to other resources, a
        dot-separated path for each relationship name can be specified:

            * GET /articles/1?include=comments.author
        '''
        r = self.test_app.get('/people/1?include=comments.author')
        people_seen = set()
        types_expected = {'people', 'comments'}
        types_seen = set()
        for item in r.json['included']:
            # Shouldn't see any types other than comments and people.
            self.assertIn(item['type'], types_expected)
            types_seen.add(item['type'])

            # We should only see people 1, and only once.
            if item['type'] == 'people':
                self.assertNotIn(item['id'], people_seen)
                people_seen.add(item['id'])

        # We should have seen at least one of each type.
        self.assertIn('people', types_seen)
        self.assertIn('comments', types_seen)



    def test_spec_multiple_include(self):
        '''Should return multiple related resource types.

        Multiple related resources can be requested in a comma-separated list:

            * GET /articles/1?include=author,comments.author
        '''
        # TODO(Colin) implement

    def test_spec_compound_full_linkage(self):
        '''All included resources should be referenced by a resource link.

        Compound documents require "full linkage", meaning that every included
        resource MUST be identified by at least one resource identifier object
        in the same document. These resource identifier objects could either be
        primary data or represent resource linkage contained within primary or
        included resources.
        '''
        # get a person with included blogs and comments.
        person = self.test_app.get('/people/1?include=blogs,comments').json
        # Find all the resource identifiers.
        rids = set()
        for rel in person['data']['relationships'].values():
            for item in rel['data']:
                rids.add((item['type'], item['id']))

        # Every included item should have an identifier somewhere.
        for item in person['included']:
            type_ = item['type']
            id_ = item['id']
            self.assertIn((type_, id_), rids)

    def test_spec_compound_no_linkage_sparse(self):
        '''Included resources not referenced if referencing field not included.

        The only exception to the full linkage requirement is when relationship
        fields that would otherwise contain linkage data are excluded via sparse
        fieldsets.
        '''
        person = self.test_app.get(
            '/people/1?include=blogs&fields[people]=name,comments'
        ).json
        # Find all the resource identifiers.
        rids = set()
        for rel in person['data']['relationships'].values():
            for item in rel['data']:
                rids.add((item['type'], item['id']))
        self.assertGreater(len(person['included']), 0)
        for blog in person['included']:
            self.assertEqual(blog['type'], 'blogs')

    def test_spec_compound_unique_resources(self):
        '''Each resource object should appear only once.

        A compound document MUST NOT include more than one resource object for
        each type and id pair.
        '''
        # get some people with included blogs and comments.
        people = self.test_app.get('/people?include=blogs,comments').json
        # Check that each resource only appears once.
        seen = set()
        # Add the main resource objects.
        for person in people['data']:
            self.assertNotIn((person['type'], person['id']), seen)
            seen.add((person['type'], person['id']))
        # Check the included resources.
        for obj in people['included']:
            self.assertNotIn((obj['type'], obj['id']), seen)
            seen.add((obj['type'], obj['id']))

    def test_spec_links(self):
        '''Links should be an object with URL strings.

        Where specified, a links member can be used to represent links. The
        value of each links member MUST be an object (a "links object").

        Each member of a links object is a “link”. A link MUST be represented as
        either:

            * a string containing the link’s URL.
            * an object ("link object") which can contain the following members:
                * href: a string containing the link’s URL.
                * meta: a meta object containing non-standard meta-information
                 about the link.

        Note: only URL string links are currently generated by jsonapi.
        '''
        links = self.test_app.get('/people').json['links']
        self.assertIsInstance(links['self'], str)
        self.assertIsInstance(links['first'], str)
        self.assertIsInstance(links['last'], str)

    def test_spec_fetch_non_existent(self):
        '''Should 404 when fetching non existent resource.

        A server MUST respond with 404 Not Found when processing a request to
        fetch a single resource that does not exist,
        '''
        r = self.test_app.get('/people/1000', status=404)

    def test_spec_fetch_non_existent_related(self):
        '''Should return primary data of null, not 404.

        null is only an appropriate response when the requested URL is one that
        might correspond to a single resource, but doesn’t currently.
        '''
        data = self.test_app.get('/comments/5/author').json['data']
        self.assertIsNone(data)

    def test_spec_fetch_relationship_link(self):
        '''relationships links should return linkage information.

        A server MUST support fetching relationship data for every relationship
        URL provided as a self link as part of a relationship’s links object

        The primary data in the response document MUST match the appropriate
        value for resource linkage, as described above for relationship objects.
        '''
        # Blogs have both many to one and one to many relationships.
        blog1 = self.test_app.get('/blogs/1').json['data']

        # to one
        owner_url = blog1['relationships']['owner']['links']['self']
        # A server MUST support fetching relationship data...
        owner_data = self.test_app.get(owner_url).json['data']
        # the response document MUST match the appropriate value for resource
        # linkage...
        #
        # In this case a resource identifier with type = 'people' and an id.
        self.assertEqual('people', owner_data['type'])
        self.assertIn('id', owner_data)

        # to one, empty relationship

        # to many
        posts_url = blog1['relationships']['posts']['links']['self']
        # A server MUST support fetching relationship data...
        posts_data = self.test_app.get(posts_url).json['data']
        # the response document MUST match the appropriate value for resource
        # linkage...
        #
        # In this case an array of 'posts' resource identifiers.
        self.assertIsInstance(posts_data, list)
        for post in posts_data:
            self.assertEqual('posts', post['type'])
            self.assertIn('id', post)

    def test_spec_fetch_relationship_to_one_empty(self):
        '''Fetching empty relationships link should give null data.

        If [a to-one] relationship is empty, then a GET request to the
        [relationship] URL would return:

            "data": null
        '''
        # comment 5 has no author
        comment5 = self.test_app.get('/comments/5').json['data']
        author = self.test_app.get(
            comment5['relationships']['author']['links']['self']
        ).json['data']
        self.assertIsNone(author)

    def test_spec_fetch_relationship_to_many_empty(self):
        '''Fetching empty relationships link should give empty array.

        If [a to-many] relationship is empty, then a GET request to the
        [relationship] URL would return:

            "data": []
        '''
        # post 1 has no comments
        post1 = self.test_app.get('/posts/1').json['data']
        comments = self.test_app.get(
            post1['relationships']['comments']['links']['self']
        ).json['data']
        self.assertEqual(len(comments), 0)

    def test_spec_fetch_not_found_relationship(self):
        '''Should 404 when fetching a relationship that does not exist.

        A server MUST return 404 Not Found when processing a request to fetch a
        relationship link URL that does not exist.
        '''
        # Try to get the author of a non existent post.
        r = self.test_app.get('/posts/1000/relationships/author', status=404)

    def test_spec_sparse_fields(self):
        '''Should return only requested fields.

        A client MAY request that an endpoint return only specific fields in the
        response on a per-type basis by including a fields[TYPE] parameter.

        The value of the fields parameter MUST be a comma-separated (U+002C
        COMMA, ",") list that refers to the name(s) of the fields to be
        returned.

        If a client requests a restricted set of fields for a given resource
        type, an endpoint MUST NOT include additional fields in resource objects
        of that type in its response.
        '''
        # Ask for just the title, content and author fields of a post.
        r = self.test_app.get('/posts/1?fields[posts]=title,content,author')
        data = r.json['data']

        atts = data['attributes']
        self.assertEqual(len(atts), 2)
        self.assertIn('title', atts)
        self.assertIn('content', atts)

        rels = data['relationships']
        self.assertEqual(len(rels), 1)
        self.assertIn('author', rels)


    def test_spec_single_sort(self):
        '''Should return  collection sorted by correct field.

        An endpoint MAY support requests to sort the primary data with a sort
        query parameter. The value for sort MUST represent sort fields.

            * GET /people?sort=age
        '''
        data = self.test_app.get('/posts?sort=content').json['data']
        prev = ''
        for item in data:
            self.assertGreaterEqual(item['attributes']['content'], prev)
            prev = item['attributes']['content']


    def test_spec_multiple_sort(self):
        '''Should return collection sorted by multiple fields, applied in order.

        An endpoint MAY support multiple sort fields by allowing comma-separated
        (U+002C COMMA, ",") sort fields. Sort fields SHOULD be applied in the
        order specified.

            * GET /people?sort=age,name
        '''
        data = self.test_app.get('/posts?sort=content,id').json['data']
        prev_content = ''
        prev_id = 0
        for item in data:
            self.assertGreaterEqual(
                item['attributes']['content'],
                prev_content
            )
            if item['attributes']['content'] != prev_content:
                prev_id = 0
            self.assertGreaterEqual(int(item['id']), prev_id)
            prev_content = item['attributes']['content']
            prev_id = int(item['id'])

    def test_spec_descending_sort(self):
        '''Should return results sorted by field in reverse order.

        The sort order for each sort field MUST be ascending unless it is
        prefixed with a minus (U+002D HYPHEN-MINUS, "-"), in which case it MUST
        be descending.

            * GET /articles?sort=-created,title
        '''
        data = self.test_app.get('/posts?sort=-content').json['data']
        prev = 'zzz'
        for item in data:
            self.assertLessEqual(item['attributes']['content'], prev)
            prev = item['attributes']['content']

    # TODO(Colin) repeat sort tests for other collection returning endpoints,
    # because: Note: This section applies to any endpoint that responds with a
    # resource collection as primary data, regardless of the request type

    def test_spec_pagination_links(self):
        '''Should provide correct pagination links.

        A server MAY provide links to traverse a paginated data set ("pagination
        links").

        Pagination links MUST appear in the links object that corresponds to a
        collection. To paginate the primary data, supply pagination links in the
        top-level links object. To paginate an included collection returned in a
        compound document, supply pagination links in the corresponding links
        object.

        The following keys MUST be used for pagination links:

            * first: the first page of data
            * last: the last page of data
            * prev: the previous page of data
            * next: the next page of data
        '''
        json = self.test_app.get('/posts?page[limit]=2&page[offset]=2').json
        self.assertEqual(len(json['data']), 2)
        self.assertIn('first', json['links'])
        self.assertIn('last', json['links'])
        self.assertIn('prev', json['links'])
        self.assertIn('next', json['links'])

    def test_spec_pagination_unavailable_links(self):
        '''Next page link should not be available

        Keys MUST either be omitted or have a null value to indicate that a
        particular link is unavailable.
        '''
        r = self.test_app.get('/posts?page[limit]=1')
        available = r.json['meta']['results']['available']
        json = self.test_app.get(
            '/posts?page[limit]=2&page[offset]=' + str(available - 2)
        ).json
        self.assertEqual(len(json['data']), 2)
        self.assertNotIn('next', json['links'])

    def test_spec_pagination_order(self):
        '''Pages (and results) should order restults as per order param.

        Concepts of order, as expressed in the naming of pagination links, MUST
        remain consistent with JSON API’s sorting rules.
        '''
        data = self.test_app.get(
            '/posts?page[limit]=4&sort=content&fields[posts]=content'
        ).json['data']
        self.assertEqual(len(data), 4)
        prev = ''
        for item in data:
            self.assertGreaterEqual(item['attributes']['content'], prev)
            prev = item['attributes']['content']

    # TODO(Colin) repeat sort tests for other collection returning endpoints,
    # because: Note: This section applies to any endpoint that responds with a
    # resource collection as primary data, regardless of the request type

    def test_spec_filterop_eq(self):
        '''Should return collection with just the alice people object.

        The filter query parameter is reserved for filtering data. Servers and
        clients SHOULD use this key for filtering operations.
        '''
        data = self.test_app.get('/people?filter[name:eq]=alice').json['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['type'], 'people')
        self.assertEqual(data[0]['attributes']['name'], 'alice')

    def test_spec_filterop_ne(self):
        '''Should return collection of people whose name is not alice.'''
        data = self.test_app.get('/people?filter[name:ne]=alice').json['data']
        for item in data:
            try:
                errors = item['meta']['errors']
            except KeyError:
                self.assertNotEqual('alice', item['attributes']['name'])

    def test_spec_filterop_startswith(self):
        '''Should return collection where titles start with "post1".'''
        data = self.test_app.get(
            '/posts?filter[title:startswith]=post1'
        ).json['data']
        for item in data:
            self.assertTrue(item['attributes']['title'].startswith('post1'))

    def test_spec_filterop_endswith(self):
        '''Should return collection where titles end with "main".'''
        data = self.test_app.get(
            '/posts?filter[title:endswith]=main'
        ).json['data']
        for item in data:
            self.assertTrue(item['attributes']['title'].endswith('main'))

    def test_spec_filterop_contains(self):
        '''Should return collection where titles contain "bob".'''
        data = self.test_app.get(
            '/posts?filter[title:contains]=bob'
        ).json['data']
        for item in data:
            self.assertTrue('bob' in item['attributes']['title'])

    def test_spec_filterop_lt(self):
        '''Should return posts with published_at less than 2015-01-03.'''
        data = self.test_app.get(
            '/posts?filter[published_at:lt]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertLess(date, ref_date)

    def test_spec_filterop_gt(self):
        '''Should return posts with published_at greater than 2015-01-03.'''
        data = self.test_app.get(
            '/posts?filter[published_at:gt]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertGreater(date, ref_date)

    def test_spec_filterop_le(self):
        '''Should return posts with published_at <= 2015-01-03.'''
        data = self.test_app.get(
            '/posts?filter[published_at:le]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertLessEqual(date, ref_date)

    def test_spec_filterop_ge(self):
        '''Should return posts with published_at >= 2015-01-03.'''
        data = self.test_app.get(
            '/posts?filter[published_at:ge]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertGreaterEqual(date, ref_date)

    ###############################################
    # POST tests.
    ###############################################

    def test_spec_post_collection(self):
        '''Should create a new person object.'''
        # Make sure there is no test person.
        data = self.test_app.get('/people?filter[name:eq]=test').json['data']
        self.assertEqual(len(data),0)

        # Try adding a test person.
        self.test_app.post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        )

        # Make sure they are there.
        data = self.test_app.get('/people?filter[name:eq]=test').json['data']
        self.assertEqual(len(data),1)

    def test_spec_post_must_have_type(self):
        '''Server should respond with 409 (Conflict) if type not specified.

        Note: The type member is required in every resource object throughout
        requests and responses in JSON API. There are some cases, such as when
        POSTing to an endpoint representing heterogenous data, when the type
        could not be inferred from the endpoint. However, picking and choosing
        when it is required would be confusing; it would be hard to remember
        when it was required and when it was not. Therefore, to improve
        consistency and minimize confusion, type is always required.
        '''
        self.test_app.post_json(
            '/people',
            {
                'data': {
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )

    def test_spec_post_with_relationships_manytoone(self):
        '''Should create a blog belonging to alice.

        If a relationship is provided in the relationships member of the
        resource object, its value MUST be a relationship object with a data
        member. The value of this key represents the linkage the new resource is
        to have.
        '''
        # Add a test blog with owner alice.
        created_id = self.test_app.post_json(
            '/blogs',
            {
                'data': {
                    'type': 'blogs',
                    'attributes': {
                        'title': 'test'
                    },
                    'relationships': {
                        'owner': {
                            'data': {'type': 'people', 'id': '1'}
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']['id']

        # Make sure they are there.
        data = self.test_app.get(
            '/blogs/{}'.format(created_id)
        ).json['data']
        self.assertEqual(data['id'], created_id)

    def test_spec_post_with_relationships_onetomany(self):
        '''Should create a two new blogs and a user who owns them.

        If a relationship is provided in the relationships member of the
        resource object, its value MUST be a relationship object with a data
        member. The value of this key represents the linkage the new resource is
        to have.
        '''
        # Add two test blogs first.
        blog1_id = self.test_app.post_json(
            '/blogs',
            {
                'data': {
                    'type': 'blogs',
                    'attributes': {
                        'title': 'test1'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']['id']
        blog2_id = self.test_app.post_json(
            '/blogs',
            {
                'data': {
                    'type': 'blogs',
                    'attributes': {
                        'title': 'test2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']['id']

        # Add a test user who owns both blogs.
        person_id = self.test_app.post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    },
                    'relationships': {
                        'blogs': {
                            'data': [
                                {'type': 'blogs', 'id': str(blog1_id)},
                                {'type': 'blogs', 'id': str(blog2_id)}
                            ]
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']['id']

        # Make sure the person exists and does own the blogs.
        data = self.test_app.get(
            '/people/{}'.format(person_id)
        ).json['data']
        self.assertEqual(data['id'], person_id)
        created_blog_ids = {blog1_id, blog2_id}
        found_blog_ids = set()
        for blog in data['relationships']['blogs']['data']:
            found_blog_ids.add(blog['id'])
        self.assertEqual(created_blog_ids, found_blog_ids)

    def test_spec_post_with_relationships_manytomany_table(self):
        '''Should create an article_by_assoc with two authors.
        '''
        # Create article_by_assoc with authors alice and bob.
        article_id = self.test_app.post_json(
            '/articles_by_assoc',
            {
                'data': {
                    "type": "articles_by_assoc",
                    "attributes": {
                        "title": "test1"
                    },
                    "relationships": {
                        "authors": {
                            "data": [
                                {"type": "people", "id": "1"},
                                {"type": "people", "id": "2"}
                            ]
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']['id']

        # GET it back and check that authors is correct.
        data = self.test_app.get(
            '/articles_by_assoc/{}'.format(article_id)
        ).json['data']
        created_people_ids = {"1", "2"}
        found_people_ids = {
            person['id'] for person in data['relationships']['authors']['data']
        }
        self.assertEqual(created_people_ids, found_people_ids)

    def test_spec_post_with_relationships_manytomany_object(self):
        '''Should create an article_by_obj with two authors.
        '''
        # Create the article_by_obj.
        article_id = self.test_app.post_json(
            '/articles_by_obj',
            {
                'data': {
                    "type": "articles_by_obj",
                    "attributes": {
                        "title": "test1"
                    },
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']['id']

        # Create the relationships to the two authors.
        rel1_id = self.test_app.post_json(
            '/article_author_associations',
            {
                'data': {
                    "type": "article_author_associations",
                    "attributes": {
                        "date_joined": "2016-01-03"
                    },
                    "relationships": {
                        "author": {
                            "data": {"type": "people", "id": "3"}
                        },
                        "article": {
                            "data": {"type": "articles", "id": article_id}
                        }
                    }
                }
            }
        ).json['data']['id']
        rel2_id = self.test_app.post_json(
            '/article_author_associations',
            {
                'data': {
                    "type": "article_author_associations",
                    "attributes": {
                        "date_joined": "2016-01-02"
                    },
                    "relationships": {
                        "author": {
                            "data": {"type": "people", "id": "2"}
                        },
                        "article": {
                            "data": {"type": "articles", "id": article_id}
                        }
                    }
                }
            }
        ).json['data']['id']

        # Check that the article has authors 1 and 3
        data = self.test_app.get(
            '/articles_by_obj/{}'.format(article_id)
        ).json['data']
        assoc_ids = {
            ass['id'] for ass in
                data['relationships']['author_associations']['data']
        }
        author_ids = set()
        for assoc_id in assoc_ids:
            data = self.test_app.get(
                '/article_author_associations/{}'.format(assoc_id)
            ).json['data']
            author_ids.add(data['relationships']['author']['data']['id'])
        self.assertEqual(author_ids, {'3', '2'})

    def test_spec_post_with_id(self):
        '''Should create a person object with id 1000.

        A server MAY accept a client-generated ID along with a request to create
        a resource. An ID MUST be specified with an id key. The client SHOULD
        use a properly generated and formatted UUID as described in RFC 4122

        If a POST request did not include a Client-Generated ID and the
        requested resource has been created successfully, the server MUST return
        a 201 Created status code.

        The response SHOULD include a Location header identifying the location
        of the newly created resource.

        The response MUST also include a document that contains the primary
        resource created.

        If the resource object returned by the response contains a self key in
        its links member and a Location header is provided, the value of the
        self member MUST match the value of the Location header.

        Comment: jsonapi.allow_client_ids is set in the ini file, so we should
        be able to create objects with ids.  The id strategy in test_project
        isn't RFC4122 UUID, but we're not enforcing that since there may be
        other globally unique id strategies in use.
        '''
        r = self.test_app.post_json(
            '/people',
            {
                'data': {
                    'id': '1000',
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=201 # Test the status code.
        )

        # Test for Location header.
        location = r.headers.get('Location')
        self.assertIsNotNone(location)

        # Test that json is a resource object
        data = r.json['data']
        self.assertEqual(data['id'],'1000')
        self.assertEqual(data['type'],'people')
        self.assertEqual(data['attributes']['name'], 'test')

        # Test that the Location header and the self link match.
        self.assertEqual(data['links']['self'], location)

    def test_spec_post_with_id_disallowed(self):
        '''Should 403 when attempting to create object with id.

        A server MUST return 403 Forbidden in response to an unsupported request
        to create a resource with a client-generated ID.
        '''
        # We need a test_app with different settings.
        with warnings.catch_warnings():
            # Suppress SAWarning: about Property _jsonapi_id being replaced by
            # Propery _jsonapi_id every time a new app is instantiated.
            warnings.simplefilter(
                "ignore",
                category=SAWarning
            )
            app = get_app(
                '{}/testing.ini'.format(parent_dir),
                options={'pyramid_jsonapi.allow_client_ids': 'false'}
            )
        test_app = webtest.TestApp(app)
        test_app.post_json(
            '/people',
            {
                'data': {
                    'id': '1000',
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=403
        )

    def test_spec_post_with_id_conflicts(self):
        '''Should 409 if id exists.

        A server MUST return 409 Conflict when processing a POST request to
        create a resource with a client-generated ID that already exists.
        '''
        self.test_app.post_json(
            '/people',
            {
                'data': {
                    'id': '1',
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409 # Test the status code.
        )

    def test_spec_post_type_conflicts(self):
        '''Should 409 if type does not exist.

        A server MUST return 409 Conflict when processing a POST request in
        which the resource object’s type is not among the type(s) that
        constitute the collection represented by the endpoint.
        '''
        self.test_app.post_json(
            '/people',
            {
                'data': {
                    'id': '1000',
                    'type': 'frogs',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409 # Test the status code.
        )

    def test_spec_post_relationships_onetomany(self):
        '''Should add two comments to a blog.

        If a client makes a POST request to a URL from a relationship link, the
        server MUST add the specified members to the relationship unless they
        are already present. If a given type and id is already in the
        relationship, the server MUST NOT add it again.
        '''
        # Make sure that comments/4,5 are not attached to posts/1.
        comment_ids = {
            comment['id'] for comment in
                self.test_app.get(
                    '/posts/1/relationships/comments'
                ).json['data']
        }
        self.assertNotIn('4', comment_ids)
        self.assertNotIn('5', comment_ids)

        # Add comments 4 and 5.
        self.test_app.post_json(
            '/posts/1/relationships/comments',
            {
                'data': [
                    { 'type': 'comments', 'id': '4'},
                    { 'type': 'comments', 'id': '5'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Make sure they are there.
        comment_ids = {
            comment['id'] for comment in
                self.test_app.get(
                    '/posts/1/relationships/comments'
                ).json['data']
        }
        self.assertEqual(comment_ids, {'4', '5'})

        # Make sure adding comments/4 again doesn't result in two comments/4.
        self.test_app.post_json(
            '/posts/1/relationships/comments',
            {
                'data': [
                    { 'type': 'comments', 'id': '4'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        comment_ids = [
            comment['id'] for comment in
                self.test_app.get(
                    '/posts/1/relationships/comments'
                ).json['data']
        ]
        self.assertEqual(comment_ids, ['4', '5'])

        # Make sure adding comments/1 adds to the comments list, rather than
        # replacing it.
        self.test_app.post_json(
            '/posts/1/relationships/comments',
            {
                'data': [
                    { 'type': 'comments', 'id': '1'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        comment_ids = [
            comment['id'] for comment in
                self.test_app.get(
                    '/posts/1/relationships/comments'
                ).json['data']
        ]
        self.assertEqual(comment_ids, ['1', '4', '5'])


    def test_spec_post_relationships_manytomany_assoc(self):
        '''Should add an author to an article_by_assoc.

        If a client makes a POST request to a URL from a relationship link, the
        server MUST add the specified members to the relationship unless they
        are already present. If a given type and id is already in the
        relationship, the server MUST NOT add it again.
        '''
        # Make sure that people/1,3 are not attached to articles_by_assoc/2.
        author_ids = {
            author['id'] for author in
                self.test_app.get(
                    '/articles_by_assoc/2/relationships/authors'
                ).json['data']
        }
        self.assertNotIn('1', author_ids)
        self.assertNotIn('3', author_ids)

        # Add people/1.
        self.test_app.post_json(
            '/articles_by_assoc/2/relationships/authors',
            {
                'data': [
                    { 'type': 'people', 'id': '1'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Make sure people/2 has been added.
        author_ids = {
            author['id'] for author in
                self.test_app.get(
                    '/articles_by_assoc/2/relationships/authors'
                ).json['data']
        }
        self.assertEqual(author_ids, {'1', '2'})

        # Make sure adding people/1 again doesn't result in multiple entries.
        self.test_app.post_json(
            '/articles_by_assoc/2/relationships/authors',
            {
                'data': [
                    { 'type': 'people', 'id': '1'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        author_ids = [
            author['id'] for author in
                self.test_app.get(
                    '/articles_by_assoc/2/relationships/authors'
                ).json['data']
        ]
        self.assertEqual(author_ids, ['1', '2'])

    ###############################################
    # PATCH tests.
    ###############################################

    def test_spec_patch(self):
        '''Should change alice's name to alice2'''
        # Patch alice.
        self.test_app.patch_json(
            '/people/1',
            {
                'data': {
                    'id': '1',
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # Fetch alice back...
        data = self.test_app.get('/people/1').json['data']
        # ...should now be alice2.
        self.assertEqual(data['attributes']['name'], 'alice2')

    def test_spec_patch_no_type_id(self):
        '''Should 409 if id or type do not exist.

        The PATCH request MUST include a single resource object as primary data.
        The resource object MUST contain type and id members.
        '''
        # No id.
        self.test_app.patch_json(
            '/people/1',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )
        # No type.
        self.test_app.patch_json(
            '/people/1',
            {
                'data': {
                    'id': '1',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )
        # No type or id.
        self.test_app.patch_json(
            '/people/1',
            {
                'data': {
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )

    def test_spec_patch_empty_success(self):
        '''Should return only meta, not data or links.

        A server MUST return a 200 OK status code if an update is successful,
        the client’s current attributes remain up to date, and the server
        responds only with top-level meta data. In this case the server MUST NOT
        include a representation of the updated resource(s).
        '''
        json = self.test_app.patch_json(
            '/people/1',
            {
                'data': {
                    'id': '1',
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        ).json
        self.assertIn('meta',json)
        self.assertEqual(len(json),1)

    def test_spec_patch_nonexistent(self):
        '''Should 404 when patching non existent resource.

        A server MUST return 404 Not Found when processing a request to modify a
        resource that does not exist.
        '''
        self.test_app.patch_json(
            '/people/1000',
            {
                'data': {
                    'id': '1000',
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        )

    def test_spec_patch_resources_relationships_manytoone(self):
        '''Should replace a post's author and no other relationship.

        Any or all of a resource’s relationships MAY be included in the resource
        object included in a PATCH request.

        If a request does not include all of the relationships for a resource,
        the server MUST interpret the missing relationships as if they were
        included with their current values. It MUST NOT interpret them as null
        or empty values.

        If a relationship is provided in the relationships member of a resource
        object in a PATCH request, its value MUST be a relationship object with
        a data member. The relationship’s value will be replaced with the value
        specified in this member.
        '''
        # Check that posts/1 does not have people/2 as an author.
        data = self.test_app.get('/posts/1').json['data']
        author_data = data['relationships']['author']['data']
        if author_data:
            self.assertNotEqual(author_data['id'], '2')

        # Store the blog and comments values so we can make sure that they
        # didn't change later.
        orig_blog = data['relationships']['blog']['data']
        orig_comments = data['relationships']['comments']['data']

        # PATCH posts/1 to have author people/2.
        r = self.test_app.patch_json(
            '/posts/1',
            {
                'data': {
                    'id': '1',
                    'type': 'posts',
                    'relationships': {
                        'author': {
                            'type': 'people', 'id': '2'
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that posts/1 now has people/2 as an author.
        data = self.test_app.get('/posts/1').json['data']
        author_data = data['relationships']['author']['data']
        self.assertEqual(author_data['id'], '2')

        # Check that it has the same blog and comments.
        new_blog = data['relationships']['blog']['data']
        self.assertEqual(orig_blog['id'], new_blog['id'])
        new_comments = data['relationships']['comments']['data']
        self.assertEqual(
            {item['id'] for item in orig_comments},
            {item['id'] for item in new_comments}
        )

    def test_spec_patch_resources_relationships_onetomany(self):
        '''Should replace a post's comments.
        '''
        # Check that posts/1 does not have comments/4 or comments/5.
        data = self.test_app.get('/posts/1').json['data']
        comments = data['relationships']['comments']['data']
        comment_ids = {'4', '5'}
        for comment in comments:
            self.assertNotIn(comment['id'], comment_ids)

        # PATCH posts/1 to have comments/4 and 5.
        self.test_app.patch_json(
            '/posts/1',
            {
                'data': {
                    'id': '1',
                    'type': 'posts',
                    'relationships': {
                        'comments': [
                            {'type': 'comments', 'id': '4'},
                            {'type': 'comments', 'id': '5'}
                        ]
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that posts/1 now has comments/4 and comments/5.
        data = self.test_app.get('/posts/1').json['data']
        comments = data['relationships']['comments']['data']
        found_ids = {comment['id'] for comment in comments}
        self.assertEqual(comment_ids, found_ids)

    def test_spec_patch_resources_relationships_manytomany_assoc(self):
        '''Change the authors of articles_by_assoc/2.
        '''
        author_ids = {'1', '3'}
        # Check that articles_by_assoc/2 does not have author ids 1 and 3
        data = self.test_app.get('/articles_by_assoc/2').json['data']
        authors = data['relationships']['authors']['data']
        found_ids = {author['id'] for author in authors}
        self.assertNotEqual(author_ids, found_ids)

        # PATCH articles_by_assoc/2 to have authors 1 and 3
        self.test_app.patch_json(
            '/articles_by_assoc/2',
            {
                'data': {
                    'id': '2',
                    'type': 'articles_by_assoc',
                    'relationships': {
                        'authors': [
                            {'type': 'people', 'id': '1'},
                            {'type': 'people', 'id': '3'}
                        ]
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that articles_by_assoc/2 now has authors 1 and 3
        data = self.test_app.get('/articles_by_assoc/2').json['data']
        authors = data['relationships']['authors']['data']
        found_ids = {author['id'] for author in authors}
        self.assertEqual(author_ids, found_ids)

    def test_spec_patch_relationships_toone(self):
        '''Should update the author of a post.

        The PATCH request MUST include a top-level member named data containing
        one of:

            * a resource identifier object corresponding to the new related
              resource.

            ...
        '''
        # Make sure the current author of post/1 is not people/3
        author_id = self.test_app.get(
            '/posts/1/relationships/author'
        ).json['data']['id']
        self.assertNotEqual(author_id, '3')

        # Set the author to be people/3
        self.test_app.patch_json(
            '/posts/1/relationships/author',
            {
                'data': {'type': 'people', 'id': '3'}
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Now the author should be people/3
        author_id = self.test_app.get(
            '/posts/1/relationships/author'
        ).json['data']['id']
        self.assertEqual(author_id, '3')

    def test_spec_patch_relationships_toone_null(self):
        '''Should set the post of a comment to null.

        The PATCH request MUST include a top-level member named data containing
        one of:

            ...

            * null, to remove the relationship.

        '''
        # Make sure the current post of comment/1 is not null.
        comment_id = self.test_app.get(
            '/comments/1/relationships/post'
        ).json['data']['id']
        self.assertNotEqual(comment_id, None)

        # Set the post to None.
        self.test_app.patch_json(
            '/comments/1/relationships/post',
            {
                'data': None
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Now the post should be None.
        comment = self.test_app.get(
            '/comments/1/relationships/post'
        ).json['data']
        self.assertEqual(comment, None)

    def test_spec_patch_relationships_onetomany(self):
        '''Should replace the comments for a post.

        If a client makes a PATCH request to a URL from a to-many relationship
        link, the server MUST either completely replace every member of the
        relationship, return an appropriate error response if some resources can
        not be found or accessed, or return a 403 Forbidden response if complete
        replacement is not allowed by the server.
        '''
        # Check that posts/1 does not have comments/4 or comments/5.
        comment_ids = {
            comment['id'] for comment in
            self.test_app.get('/posts/1/relationships/comments').json['data']
        }
        for cid in comment_ids:
            self.assertNotIn(cid, {'4', '5'})

        # PATCH posts/1 to have comments/4 and 5.
        self.test_app.patch_json(
            '/posts/1/relationships/comments',
            {
                'data': [
                    {'type': 'comments', 'id': '4'},
                    {'type': 'comments', 'id': '5'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Test that posts/1 has comments/4 and 5 (and only those).
        comment_ids = {
            comment['id'] for comment in
            self.test_app.get('/posts/1/relationships/comments').json['data']
        }
        self.assertEqual(comment_ids, {'4', '5'})

    def test_spec_patch_relationships_manytomany_assoc(self):
        '''Should replace the authors for an article_by_assoc.

        If a client makes a PATCH request to a URL from a to-many relationship
        link, the server MUST either completely replace every member of the
        relationship, return an appropriate error response if some resources can
        not be found or accessed, or return a 403 Forbidden response if complete
        replacement is not allowed by the server.
        '''
        author_ids = {'1', '3'}
        # Check that articles_by_assoc/2 does not have author ids 1 and 3
        found_ids = {
            author['id'] for author in
            self.test_app.get(
                '/articles_by_assoc/2/relationships/authors'
            ).json['data']
        }
        self.assertNotEqual(author_ids, found_ids)

        # PATCH articles_by_assoc/2 to have authors 1 and 3
        self.test_app.patch_json(
            '/articles_by_assoc/2/relationships/authors',
            {
                'data': [
                    {'type': 'people', 'id': '1'},
                    {'type': 'people', 'id': '3'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that articles_by_assoc/2 now has authors 1 and 3
        found_ids = {
            author['id'] for author in
            self.test_app.get(
                '/articles_by_assoc/2/relationships/authors'
            ).json['data']
        }
        self.assertEqual(author_ids, found_ids)

    ###############################################
    # DELETE tests.
    ###############################################

    def test_spec_delete_item(self):
        '''Should delete comments/5

        An individual resource can be deleted by making a DELETE request to the
        resource’s URL
        '''

        # Check that comments/5 exists.
        self.test_app.get('/comments/5')

        # Delete comments/5.
        self.test_app.delete('/comments/5')

        # Check that comments/5 no longer exists.
        self.test_app.get('/comments/5', status=404)

    def test_spec_delete_relationships_onetomany(self):
        '''Should remove a comment from a post.

        If the client makes a DELETE request to a URL from a relationship link
        the server MUST delete the specified members from the relationship or
        return a 403 Forbidden response. If all of the specified resources are
        able to be removed from, or are already missing from, the relationship
        then the server MUST return a successful response
        '''
        # Get the current set of comments for posts/4.
        comment_ids = {
            comment['id'] for comment in
            self.test_app.get('/posts/4/relationships/comments').json['data']
        }
        self.assertEqual(comment_ids, {'1', '2', '5'})

        # DELETE comments/1 and 2
        self.test_app.delete_json(
            '/posts/4/relationships/comments',
            {
                'data': [
                    {'type': 'comments', 'id': '1'},
                    {'type': 'comments', 'id': '2'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Test that posts/4 now only has comments/5
        comment_ids = {
            comment['id'] for comment in
            self.test_app.get('/posts/4/relationships/comments').json['data']
        }
        self.assertEqual(comment_ids, {'5'})

    def test_spec_delete_relationships_onetomany_double_delete(self):
        '''Should remove a comment from a post twice.

        If all of the specified resources are... already missing from, the
        relationship then the server MUST return a successful response
        '''
        # Get the current set of comments for posts/4.
        comment_ids = {
            comment['id'] for comment in
            self.test_app.get('/posts/4/relationships/comments').json['data']
        }
        self.assertEqual(comment_ids, {'1', '2', '5'})

        # DELETE comments/1.
        self.test_app.delete_json(
            '/posts/4/relationships/comments',
            {
                'data': [
                    {'type': 'comments', 'id': '1'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Test that comments/1 has been deleted.
        comment_ids = {
            comment['id'] for comment in
            self.test_app.get('/posts/4/relationships/comments').json['data']
        }
        self.assertEqual(comment_ids, {'2', '5'})

        # DELETE comments/1 again.
        self.test_app.delete_json(
            '/posts/4/relationships/comments',
            {
                'data': [
                    {'type': 'comments', 'id': '1'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # Test that we still have the same list of comments.
        comment_ids = {
            comment['id'] for comment in
            self.test_app.get('/posts/4/relationships/comments').json['data']
        }
        self.assertEqual(comment_ids, {'2', '5'})

    def test_spec_delete_relationships_manytomany_assoc(self):
        '''Should remove an author from an artile_by_assoc.

        If the client makes a DELETE request to a URL from a relationship link
        the server MUST delete the specified members from the relationship or
        return a 403 Forbidden response. If all of the specified resources are
        able to be removed from, or are already missing from, the relationship
        then the server MUST return a successful response
        '''
        found_ids = {
            author['id'] for author in
            self.test_app.get(
                '/articles_by_assoc/1/relationships/authors'
            ).json['data']
        }
        self.assertEqual(found_ids, {'1', '2'})

        # DELETE people/1 from rel.
        self.test_app.delete_json(
            '/articles_by_assoc/1/relationships/authors',
            {
                'data': [
                    {'type': 'people', 'id': '1'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that articles_by_assoc/2 now has authors 2
        found_ids = {
            author['id'] for author in
            self.test_app.get(
                '/articles_by_assoc/1/relationships/authors'
            ).json['data']
        }
        self.assertEqual(found_ids, {'2'})

    def test_spec_delete_relationships_manytomany_assoc_double_delete(self):
        '''Should double-remove an author from an artile_by_assoc.

        If all of the specified resources are... already missing from, the
        relationship then the server MUST return a successful response
        '''
        found_ids = {
            author['id'] for author in
            self.test_app.get(
                '/articles_by_assoc/1/relationships/authors'
            ).json['data']
        }
        self.assertEqual(found_ids, {'1', '2'})

        # DELETE people/1 from rel.
        self.test_app.delete_json(
            '/articles_by_assoc/1/relationships/authors',
            {
                'data': [
                    {'type': 'people', 'id': '1'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that articles_by_assoc/2 now has authors 2
        found_ids = {
            author['id'] for author in
            self.test_app.get(
                '/articles_by_assoc/1/relationships/authors'
            ).json['data']
        }
        self.assertEqual(found_ids, {'2'})

        # Try to DELETE people/1 again.
        self.test_app.delete_json(
            '/articles_by_assoc/1/relationships/authors',
            {
                'data': [
                    {'type': 'people', 'id': '1'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that articles_by_assoc/2 still has authors 2
        found_ids = {
            author['id'] for author in
            self.test_app.get(
                '/articles_by_assoc/1/relationships/authors'
            ).json['data']
        }
        self.assertEqual(found_ids, {'2'})


class TestErrors(DBTestBase):
    '''Test that erros are thrown properly.'''

    ###############################################
    # Error tests.
    ###############################################

    def test_errors_structure(self):
        '''Errors should be array of objects with code, title, detail members.'''
        r = self.test_app.get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )
        self.assertIn('errors', r.json)
        self.assertIsInstance(r.json['errors'], list)
        err = r.json['errors'][0]
        self.assertIn('code', err)
        self.assertIn('title', err)
        self.assertIn('detail', err)


class TestBugs(DBTestBase):

    def test_19_last_negative_offset(self):
        '''last link should not have negative offset.

        #19: 'last' link has negative offset if zero results are returned
        '''
        # Need an empty collection: use a filter that will not match.
        last = self.test_app.get(
            '/posts?filter[title:eq]=frog'
        ).json['links']['last']
        offset = int(
            urllib.parse.parse_qs(
                urllib.parse.urlparse(last).query
            )['page[offset]'][0]
        )
        self.assertGreaterEqual(offset, 0)

    def test_20_non_string_id(self):
        '''Creating single object should not result in integer id.

        #20: creating single object returns non string id
        '''
        data = self.test_app.post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']
        self.assertIsInstance(data['id'], str)


if __name__ == "__main__":
    unittest.main()
