// @ts-check
// The shared max-models docs setup (@max-models/starlight-theme): served at
// https://spokes3d.github.io/gallery-template/.
import { defineDocs } from '@max-models/starlight-theme';

export default defineDocs({
	repo: 'gallery-template',
	owner: 'spokes3d',
	title: 'gallery-template',
	description: 'Galleries of computational studies: cached results, honest status boxes, public and private.',
	nav: [
		{ label: 'Guides', link: '/guides/new-gallery/' },
		{ label: 'Studies', link: '/studies/' },
	],
	sidebar: [
		{
			label: 'Guides',
			items: [
				{ label: 'Starting a gallery', slug: 'guides/new-gallery' },
				{ label: 'Adding a study', slug: 'guides/studies' },
				{ label: 'Publishing studies', slug: 'guides/publishing' },
			],
		},
		{
			label: 'Studies',
			items: [{ autogenerate: { directory: 'studies' } }],
		},
	],
});
