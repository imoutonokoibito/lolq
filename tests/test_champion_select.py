import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main


class Response:
    def __init__(self, data=None, status=200):
        self.data, self.status = copy.deepcopy(data), status

    async def json(self):
        return self.data

    async def text(self):
        return 'rejected'


class Client:
    def __init__(self, outcomes=None):
        self.action = dict(id=0, actorCellId=1, type='pick', championId=0,
                           completed=False, isInProgress=True)
        self.session = dict(localPlayerCellId=1, timer={'phase': 'BAN_PICK'},
                            myTeam=[dict(cellId=1, assignedPosition='middle')],
                            actions=[[self.action]])
        self.outcomes = outcomes or {}
        self.patches = []
        self.posts = []
        self.dodge_status = {}
        self.readable = True

    async def request(self, method, path, data=None):
        await asyncio.sleep(0)
        if method == 'get':
            if path.endswith('pickable-champion-ids'):
                return Response([1, 2, 3])
            return Response(self.session) if self.readable else Response(status=404)
        if method == 'post':
            self.posts.append(path)
            return Response(status=self.dodge_status.get(path, 204))
        cid = data['championId']
        self.patches.append(cid)
        outcome = self.outcomes.get(cid, 'accept')
        if outcome == 'reject':
            return Response(status=400)
        if outcome == 'unreadable':
            self.readable = False
        elif outcome != 'ignore':
            self.action.update(data)
        if outcome == 'lost_response':
            raise ConnectionError('response lost')
        return Response(status=204)


class ChampionSelectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main.have_i_prepicked = False
        main.have_i_dodged = False
        main.champ_select_lock = asyncio.Lock()
        self.config = dict(layouts={
            'a': dict(champion='A', spells=['flash'], runes=['rune']),
            'b': dict(champion='B', spells=['ignite'], runes=['rune']),
            'c': dict(champion='C', spells=[], runes=[])},
            roles={'mid': ['a', 'b']}, fallback=dict(mode='fallback_layout', layout_id='c'))
        for name, value in [('champions_map', {'A': 1, 'B': 2, 'C': 3}),
                            ('load_config', lambda: self.config),
                            ('set_summoner_spells', AsyncMock()),
                            ('set_runes', AsyncMock())]:
            patcher = patch.object(main, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_silent_rejection_advances_and_only_sets_accepted_layout(self):
        client = Client({1: 'ignore'})
        await main.handle_champ_select(client, client.session)
        self.assertEqual(client.patches, [1, 2])
        main.set_summoner_spells.assert_awaited_once_with(client, ['ignite'])
        main.set_runes.assert_awaited_once()

    async def test_http_rejections_reach_configured_fallback(self):
        client = Client({1: 'reject', 2: 'reject'})
        await main.handle_champ_select(client, client.session)
        self.assertEqual(client.patches, [1, 2, 3])

    async def test_all_rejections_terminate(self):
        client = Client({1: 'reject', 2: 'reject', 3: 'reject'})
        await asyncio.wait_for(main.handle_champ_select(client, client.session), 1)
        self.assertEqual(client.patches, [1, 2, 3])
        main.set_runes.assert_not_awaited()

    async def test_unreadable_state_stops_fallback(self):
        client = Client({1: 'unreadable'})
        await main.handle_champ_select(client, client.session)
        self.assertEqual(client.patches, [1])
        main.set_runes.assert_not_awaited()

    async def test_lost_response_is_confirmed_from_state(self):
        client = Client({1: 'lost_response'})
        self.assertTrue(await main.verified_pick(client, client.action.copy(), 1, True))

    async def test_overlapping_updates_pick_and_apply_once(self):
        client = Client()
        event = SimpleNamespace(type='Update')
        await asyncio.gather(*(main.champ_select_changed(client, event) for _ in range(5)))
        self.assertEqual(client.patches, [1])
        main.set_runes.assert_awaited_once()

    async def test_completed_action_is_never_overwritten(self):
        client = Client()
        client.action.update(completed=True, championId=3)
        self.assertIsNone(await main.verified_pick(client, client.action.copy(), 1, True))
        self.assertEqual(client.patches, [])

    async def test_prepick_zero_action_id_and_delete_reset(self):
        client = Client()
        client.session['timer']['phase'] = 'PLANNING'
        client.action['isInProgress'] = False
        await main.champ_select_changed(client, SimpleNamespace(type='Create'))
        self.assertTrue(main.have_i_prepicked)
        self.assertFalse(client.action['completed'])
        await main.champ_select_changed(client, SimpleNamespace(type='Delete'))
        self.assertFalse(main.have_i_prepicked)

    async def test_ownership_404_falls_back_to_filtered_inventory(self):
        request = AsyncMock(side_effect=[Response(status=404), Response({'summonerId': 99}),
            Response([{'id': 1, 'ownership': {'owned': True}},
                      {'id': 2, 'ownership': {'owned': False}}])])
        self.assertEqual(await main.get_owned_champion_ids(SimpleNamespace(request=request)), {1})
        self.assertEqual(request.call_args.args[1], '/lol-champions/v1/inventories/99/champions-minimal')

    async def test_empty_ownership_is_not_unknown(self):
        client = SimpleNamespace(request=AsyncMock(return_value=Response([])))
        self.assertEqual(await main.get_owned_champion_ids(client), set())

    def test_pickability_filters_layouts_and_random_without_repeats(self):
        self.config['fallback'] = {'mode': 'random_default'}
        candidates = list(main.pick_candidates('MIDDLE', self.config, {2, 3}, {2}))
        self.assertEqual([cid for cid, _, _ in candidates], [3])
        self.assertEqual(list(main.pick_candidates('MIDDLE', self.config, set(), set())), [])

    async def test_dodge_fallback_after_role_layouts_exhausted(self):
        self.config['fallback'] = {'mode': 'dodge', 'layout_id': ''}
        client = Client({1: 'reject', 2: 'reject'})
        await main.handle_champ_select(client, client.session)
        self.assertEqual(client.patches, [1, 2])
        self.assertEqual(client.posts, [main.DODGE_PATHS[0]])
        await main.handle_champ_select(client, client.session)
        self.assertEqual(client.posts, [main.DODGE_PATHS[0]])

    async def test_dodge_tries_next_endpoint_when_rejected(self):
        self.config['fallback'] = {'mode': 'dodge', 'layout_id': ''}
        self.config['roles'] = {}
        client = Client()
        client.dodge_status = {main.DODGE_PATHS[0]: 404}
        await main.handle_champ_select(client, client.session)
        self.assertEqual(client.patches, [])
        self.assertEqual(client.posts, main.DODGE_PATHS[:2])

    async def test_no_dodge_during_planning(self):
        self.config['fallback'] = {'mode': 'dodge', 'layout_id': ''}
        self.config['roles'] = {}
        client = Client()
        client.session['timer']['phase'] = 'PLANNING'
        await main.handle_champ_select(client, client.session)
        self.assertEqual(client.posts, [])


if __name__ == '__main__':
    unittest.main()
