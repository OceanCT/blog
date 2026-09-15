'use strict';

function columns(locals) {
  const posts = locals.posts.toArray();
  const bySlug = new Map(posts.map(post => [post.slug, post]));
  return (locals.data.columns || []).map(column => ({
    ...column,
    path: `columns/${column.id}/`,
    posts: column.posts.map(slug => bySlug.get(slug)).filter(Boolean)
  })).filter(column => column.posts.length);
}

hexo.extend.helper.register('note_columns', function () {
  return columns(this.site);
});
hexo.extend.generator.register('note-columns', locals => {
  const groups = columns(locals);
  return [
    { path: 'columns/index.html', layout: 'columns', data: { title: '主题专栏' } },
    ...groups.map(column => ({
      path: `${column.path}index.html`, layout: 'column',
      data: { title: `${column.title} 专栏`, description: column.description, column_id: column.id }
    }))
  ];
});
