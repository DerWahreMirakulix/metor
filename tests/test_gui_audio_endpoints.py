"""Device-choice grouping tests; inert descriptors do not prove physical support."""

import unittest

from metor.client.platform import AudioEndpoint
from metor.ui.gui.runtime.voice.endpoints import group_endpoints


class AudioEndpointGroupingTests(unittest.TestCase):
    """Keeps friendly choices conservative and compatible native variants explicit."""

    def test_exact_windows_aliases_coalesce_and_keep_all_variants(self) -> None:
        """API suffixes stay in native variants while exact labels group together."""
        endpoints = (
            AudioEndpoint(
                0,
                'USB Headset (MME)',
                True,
                True,
                device_name='USB Headset',
                host_api='MME',
            ),
            AudioEndpoint(
                1,
                'USB Headset (Windows DirectSound)',
                True,
                True,
                device_name=' USB\t HEADSET ',
                host_api='Windows DirectSound',
            ),
            AudioEndpoint(
                2,
                'USB Headset (Windows WASAPI)',
                True,
                True,
                device_name='usb headset',
                host_api='Windows WASAPI',
            ),
        )

        groups = group_endpoints(endpoints, microphone=False)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].name, 'USB Headset')
        self.assertIs(groups[0].preferred, endpoints[0])
        self.assertEqual(groups[0].variants, endpoints)

    def test_unsupported_first_alias_prefers_compatible_variant(self) -> None:
        """Observed format results choose a route without preferring an API name."""
        endpoints = (
            AudioEndpoint(
                0,
                'Headset (MME)',
                True,
                True,
                output_error='Unsupported format',
                device_name='Headset',
                host_api='MME',
            ),
            AudioEndpoint(
                1,
                'Headset (Windows WASAPI)',
                True,
                True,
                device_name='Headset',
                host_api='Windows WASAPI',
            ),
        )

        group = group_endpoints(endpoints, microphone=False)[0]

        self.assertIs(group.preferred, endpoints[1])
        self.assertEqual(group.variants, endpoints)

    def test_selected_compatible_variant_is_retained(self) -> None:
        """A deliberate compatible route survives friendly device grouping."""
        endpoints = (
            AudioEndpoint(3, 'Headset (MME)', True, True, device_name='Headset'),
            AudioEndpoint(8, 'Headset (WASAPI)', True, True, device_name='Headset'),
        )

        group = group_endpoints(endpoints, microphone=True, selected=8)[0]

        self.assertIs(group.preferred, endpoints[1])

    def test_selected_unsupported_variant_does_not_mask_compatible_alias(self) -> None:
        """A remembered unsupported choice leaves the usable alias preferred."""
        endpoints = (
            AudioEndpoint(
                3,
                'Headset (MME)',
                True,
                True,
                input_error='Unsupported format',
                device_name='Headset',
            ),
            AudioEndpoint(8, 'Headset (WASAPI)', True, True, device_name='Headset'),
        )

        group = group_endpoints(endpoints, microphone=True, selected=3)[0]

        self.assertIs(group.preferred, endpoints[1])
        self.assertEqual(group.variants, endpoints)

    def test_similar_labels_remain_separate_in_enumeration_order(self) -> None:
        """Distinct labels and channel suffixes are never guessed into one device."""
        endpoints = (
            AudioEndpoint(4, 'Headset 2 (MME)', True, True, device_name='Headset 2'),
            AudioEndpoint(1, 'Headset (MME)', True, True, device_name='Headset'),
            AudioEndpoint(
                2,
                'Headset (Hands-Free) (MME)',
                True,
                True,
                device_name='Headset (Hands-Free)',
            ),
            AudioEndpoint(7, 'Headset 2 (WASAPI)', True, True, device_name='Headset 2'),
        )

        groups = group_endpoints(endpoints, microphone=False)

        self.assertEqual(
            tuple(group.name for group in groups),
            ('Headset 2', 'Headset', 'Headset (Hands-Free)'),
        )
        self.assertEqual(groups[0].variants, (endpoints[0], endpoints[3]))
        self.assertEqual(groups[1].variants, (endpoints[1],))
        self.assertEqual(groups[2].variants, (endpoints[2],))

    def test_legacy_display_names_are_not_parsed_or_rewritten(self) -> None:
        """Descriptors without separate device names retain their original labels."""
        endpoints = (
            AudioEndpoint(0, '  Headset (MME)  ', True, True),
            AudioEndpoint(1, 'Headset (Windows WASAPI)', True, True),
        )

        groups = group_endpoints(endpoints, microphone=False)

        self.assertEqual(
            tuple(group.name for group in groups),
            (
                '  Headset (MME)  ',
                'Headset (Windows WASAPI)',
            ),
        )
        self.assertEqual(tuple(group.preferred for group in groups), endpoints)

    def test_direction_filters_variants_and_checks_its_own_format(self) -> None:
        """Input and output availability and compatibility are independent."""
        endpoints = (
            AudioEndpoint(
                0,
                'Headset input',
                True,
                False,
                input_error='Unsupported format',
                device_name='Headset',
            ),
            AudioEndpoint(1, 'Headset output', False, True, device_name='Headset'),
            AudioEndpoint(
                2,
                'Headset duplex',
                True,
                True,
                output_error='Unsupported format',
                device_name='Headset',
            ),
        )

        input_group = group_endpoints(endpoints, microphone=True, selected=1)[0]
        output_group = group_endpoints(endpoints, microphone=False, selected=2)[0]

        self.assertEqual(input_group.variants, (endpoints[0], endpoints[2]))
        self.assertIs(input_group.preferred, endpoints[2])
        self.assertEqual(output_group.variants, (endpoints[1], endpoints[2]))
        self.assertIs(output_group.preferred, endpoints[1])

    def test_all_unsupported_variants_remain_visible_in_original_order(self) -> None:
        """The first unsupported route represents a group when no alias is usable."""
        endpoints = (
            AudioEndpoint(
                3,
                'Headset (MME)',
                True,
                True,
                output_error='Unsupported format',
                device_name='Headset',
            ),
            AudioEndpoint(
                1,
                'Headset (WASAPI)',
                True,
                True,
                output_error='Unsupported format',
                device_name='Headset',
            ),
        )

        group = group_endpoints(endpoints, microphone=False, selected=1)[0]

        self.assertIs(group.preferred, endpoints[0])
        self.assertEqual(group.variants, endpoints)

    def test_no_direction_available_returns_no_choices(self) -> None:
        """Unavailable directions and empty enumeration produce an empty chooser."""
        output_only = AudioEndpoint(0, 'Speakers', False, True)
        input_only = AudioEndpoint(1, 'Microphone', True, False)

        self.assertEqual(group_endpoints((), microphone=True), ())
        self.assertEqual(group_endpoints((output_only,), microphone=True), ())
        self.assertEqual(group_endpoints((input_only,), microphone=False), ())
